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

        table = dynamodb.TableV2(self, "Transactions",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            removal_policy=removal,
            deletion_protection=is_prod,
        )

        # Log group dichiarato nel codice: così lo stack lo possiede e il destroy lo cancella
        log_group = logs.LogGroup(self, "HandlerLogs",
            retention=logs.RetentionDays.ONE_MONTH if is_prod else logs.RetentionDays.ONE_WEEK,
            removal_policy=removal,
        )

        powertools = _lambda.LayerVersion.from_layer_version_arn(self, "Powertools",
            f"arn:aws:lambda:{Aws.REGION}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:44",
        )
        
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

        api = apigw.LambdaRestApi(self, "Api", handler=fn,
            deploy_options=apigw.StageOptions(tracing_enabled=True),
        )
        CfnOutput(self, "ApiUrl", value=api.url)

                # --- Notifiche: topic SNS, email solo in prod ---
        alarm_topic = sns.Topic(self, "AlarmTopic")
        alarm_email = self.node.try_get_context("alarm_email")
        if is_prod and alarm_email:
            alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))

        # --- Alarm sui sintomi visibili all'utente ---
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
        for alarm in alarms:
            alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
            alarm.add_ok_action(cw_actions.SnsAction(alarm_topic))