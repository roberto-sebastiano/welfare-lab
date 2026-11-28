import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()
metrics = Metrics()
metrics.set_default_dimensions(stage=os.environ["STAGE"])

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
events_client = boto3.client("events")


@tracer.capture_method
def save_transaction() -> dict:
    item = {"pk": str(uuid.uuid4()), "createdAt": datetime.now(timezone.utc).isoformat()}
    table.put_item(Item=item)
    return item


@tracer.capture_method
def publish_event(item: dict, poison: bool = False) -> None:
    detail = {**item, "poison": True} if poison else item
    response = events_client.put_events(Entries=[{
        "EventBusName": os.environ["EVENT_BUS_NAME"],
        "Source": "welfare-lab.api",
        "DetailType": "TransactionCreated",
        "Detail": json.dumps(detail),
    }])
    if response["FailedEntryCount"]:
        raise RuntimeError(f"Pubblicazione evento fallita: {response['Entries']}")


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    params = event.get("queryStringParameters") or {}
    if params.get("fail") == "1":
        logger.error("Errore simulato richiesto")
        raise RuntimeError("Errore simulato per testare gli alarm")

    item = save_transaction()
    publish_event(item, poison=params.get("poison") == "1")

    logger.info("Transazione creata", extra={"pk": item["pk"]})
    metrics.add_metric(name="TransactionCreated", unit=MetricUnit.Count, value=1)
    return {"statusCode": 200, "body": json.dumps(item)}