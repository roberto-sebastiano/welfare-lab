from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput, Aws, Duration,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_logs as logs,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
)
from constructs import Construct


class WelfareLabStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_prod = stage == "prod"
        removal = RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY

        # --- Dati ---
        table = dynamodb.TableV2(self, "Transactions",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            removal_policy=removal,
            deletion_protection=is_prod,
        )

        # --- Log group dichiarato nel codice: lo stack lo possiede e il destroy lo cancella ---
        log_group = logs.LogGroup(self, "HandlerLogs",
            retention=logs.RetentionDays.ONE_MONTH if is_prod else logs.RetentionDays.ONE_WEEK,
            removal_policy=removal,
        )

        # --- Powertools (layer pubblico di AWS) ---
        powertools = _lambda.LayerVersion.from_layer_version_arn(self, "Powertools",
            f"arn:aws:lambda:{Aws.REGION}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:44",
        )

        # --- Lambda ---
        fn = _lambda.Function(self, "Handler",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda"),
            log_group=log_group,
            layers=[powertools],
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                "STAGE": stage,
                "POWERTOOLS_SERVICE_NAME": "welfare-lab",
                "POWERTOOLS_METRICS_NAMESPACE": "WelfareLab",
                "POWERTOOLS_LOG_LEVEL": "INFO",
            },
        )

        table.grant_read_write_data(fn)

        # --- API ---
        api = apigw.LambdaRestApi(self, "Api", handler=fn,
            deploy_options=apigw.StageOptions(tracing_enabled=True),
        )
        CfnOutput(self, "ApiUrl", value=api.url)

        # --- Notifiche: topic SNS, email solo in prod ---
        alarm_topic = sns.Topic(self, "AlarmTopic")
        alarm_email = self.node.try_get_context("alarm_email")
        if is_prod and alarm_email:
            alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))

        # --- Alarm a soglia sui sintomi visibili all'utente ---
        alarms = [
            cw.Alarm(self, "LambdaErrors",
                alarm_name=f"{self.stack_name}-lambda-errors",
                metric=fn.metric_errors(period=Duration.minutes(1), statistic="Sum"),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ),
            cw.Alarm(self, "Api5xx",
                alarm_name=f"{self.stack_name}-api-5xx",
                metric=api.metric_server_error(period=Duration.minutes(1), statistic="Sum"),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ),
            cw.Alarm(self, "ApiLatencyP99",
                alarm_name=f"{self.stack_name}-api-latency-p99",
                metric=api.metric_latency(period=Duration.minutes(5), statistic="p99"),
                threshold=1000,           # millisecondi
                evaluation_periods=3,
                datapoints_to_alarm=2,    # 2 periodi su 3: meno falsi allarmi
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ),
        ]

        # Gli alarm a conteggio restano visibili in console e in dashboard.
        # Per gli errori ora notifica lo SLO; resta la notifica sulla latenza.
        latency_alarm = alarms[-1]
        latency_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
        latency_alarm.add_ok_action(cw_actions.SnsAction(alarm_topic))

        # --- SLO di disponibilità: 99,9% delle richieste senza 5xx ---
        error_budget = 0.001   # 1 - 0.999

        def errors_math(window: Duration, key: str, formula: str, label: str = None) -> cw.MathExpression:
            """Espressione su richieste ed errori 5xx di API Gateway in una finestra temporale.
            key rende unici gli id delle metriche quando più espressioni stanno nello stesso grafico."""
            req, err = f"req{key}", f"err{key}"
            return cw.MathExpression(
                expression=formula.format(req=req, err=err),
                using_metrics={
                    req: api.metric_count(period=window, statistic="Sum"),
                    err: api.metric_server_error(period=window, statistic="Sum"),
                },
                period=window,
                label=label,
            )

        def burn_rate_alarm(key: str, window: Duration, burn_rate: float) -> cw.Alarm:
            # Tasso di errore nella finestra > burn_rate × budget
            return cw.Alarm(self, f"BurnRate{key}",
                alarm_name=f"{self.stack_name}-burn-rate-{key}",
                metric=errors_math(window, key, "IF({req} > 0, {err} / {req}, 0)"),
                threshold=burn_rate * error_budget,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )

        slo_page = cw.CompositeAlarm(self, "SloPage",
            composite_alarm_name=f"{self.stack_name}-slo-page",
            alarm_description="Burn rate 14,4x su 1h e 5m: a questo ritmo il budget mensile finisce in circa 2 giorni",
            alarm_rule=cw.AlarmRule.all_of(
                burn_rate_alarm("1h", Duration.hours(1), 14.4),
                burn_rate_alarm("5m", Duration.minutes(5), 14.4),
            ),
        )
        slo_ticket = cw.CompositeAlarm(self, "SloTicket",
            composite_alarm_name=f"{self.stack_name}-slo-ticket",
            alarm_description="Burn rate 6x su 6h e 30m: a questo ritmo il budget mensile finisce in 5 giorni",
            alarm_rule=cw.AlarmRule.all_of(
                burn_rate_alarm("6h", Duration.hours(6), 6),
                burn_rate_alarm("30m", Duration.minutes(30), 6),
            ),
        )
        for slo_alarm in (slo_page, slo_ticket):
            slo_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
            slo_alarm.add_ok_action(cw_actions.SnsAction(alarm_topic))

        # --- Dashboard ---
        burn_formula = f"IF({{req}} > 0, ({{err}} / {{req}}) / {error_budget}, 0)"

        dashboard = cw.Dashboard(self, "Dashboard",
            dashboard_name=f"{self.stack_name}-overview",
            default_interval=Duration.hours(3),
        )
        dashboard.add_widgets(
            cw.SingleValueWidget(
                title="Disponibilità nel periodo selezionato (%) - SLO 99,9%",
                metrics=[errors_math(Duration.minutes(5), "Avail",
                    "100 * (1 - IF({req} > 0, {err} / {req}, 0))", "Disponibilità")],
                set_period_to_time_range=True,
                width=8,
            ),
            cw.AlarmStatusWidget(
                title="Stato alarm",
                alarms=[slo_page, slo_ticket, *alarms],
                width=16,
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Richieste e 5xx (al minuto)",
                left=[api.metric_count(period=Duration.minutes(1), statistic="Sum", label="Richieste")],
                right=[api.metric_server_error(period=Duration.minutes(1), statistic="Sum", label="5xx")],
                width=8,
            ),
            cw.GraphWidget(
                title="Latenza API (ms)",
                left=[
                    api.metric_latency(period=Duration.minutes(1), statistic="p50", label="p50"),
                    api.metric_latency(period=Duration.minutes(1), statistic="p99", label="p99"),
                ],
                width=8,
            ),
            cw.GraphWidget(
                title="Burn rate dell'error budget",
                left=[
                    errors_math(Duration.minutes(5), "B5m", burn_formula, "Burn rate 5 min"),
                    errors_math(Duration.hours(1), "B1h", burn_formula, "Burn rate 1 h"),
                ],
                left_annotations=[
                    cw.HorizontalAnnotation(value=14.4, label="Page 14,4x", color=cw.Color.RED),
                    cw.HorizontalAnnotation(value=6, label="Ticket 6x", color=cw.Color.ORANGE),
                ],
                width=8,
            ),
        )