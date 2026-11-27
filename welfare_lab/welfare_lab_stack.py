from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_logs as logs,
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

        fn = _lambda.Function(self, "Handler",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda"),
            log_group=log_group,
            environment={"TABLE_NAME": table.table_name, "STAGE": stage, "VERSION": "2"},
        )

        table.grant_read_write_data(fn)
        

        api = apigw.LambdaRestApi(self, "Api", handler=fn)
        CfnOutput(self, "ApiUrl", value=api.url)