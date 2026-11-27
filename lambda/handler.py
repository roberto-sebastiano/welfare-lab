import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()      # traccia in automatico anche le chiamate boto3 a DynamoDB
metrics = Metrics()
metrics.set_default_dimensions(stage=os.environ["STAGE"])

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


@tracer.capture_method
def save_transaction() -> dict:
    item = {"pk": str(uuid.uuid4()), "createdAt": datetime.now(timezone.utc).isoformat()}
    table.put_item(Item=item)
    return item


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    item = save_transaction()
    logger.info("Transazione creata", extra={"pk": item["pk"]})
    metrics.add_metric(name="TransactionCreated", unit=MetricUnit.Count, value=1)
    return {"statusCode": 200, "body": json.dumps(item)}