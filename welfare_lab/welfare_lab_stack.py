from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
)
from constructs import Construct


class WelfareLabStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.TableV2(self, "Transactions",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            removal_policy=RemovalPolicy.DESTROY,  # solo per l'esercizio!
        )

        fn = _lambda.Function(self, "Handler",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda"),
            environment={"TABLE_NAME": table.table_name},
        )

        table.grant_read_write_data(fn)

        api = apigw.LambdaRestApi(self, "Api", handler=fn)
        CfnOutput(self, "ApiUrl", value=api.url)