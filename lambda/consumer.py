import json
import os

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer, IdempotencyConfig, idempotent_function,
)

logger = Logger()
tracer = Tracer()
metrics = Metrics()
metrics.set_default_dimensions(stage=os.environ["STAGE"])

processor = BatchProcessor(event_type=EventType.SQS)
persistence = DynamoDBPersistenceLayer(table_name=os.environ["IDEMPOTENCY_TABLE"])
# La chiave di idempotenza è il pk della transazione: stesso pk = stessa operazione
idempotency_config = IdempotencyConfig(event_key_jmespath="pk", expires_after_seconds=3600)


@idempotent_function(data_keyword_argument="transaction", persistence_store=persistence, config=idempotency_config)
def process_transaction(transaction: dict) -> dict:
    if transaction.get("poison"):
        raise ValueError("Messaggio non elaborabile")
    logger.info("Elaboro transazione", extra={"pk": transaction["pk"]})
    metrics.add_metric(name="TransactionProcessed", unit=MetricUnit.Count, value=1)
    return {"pk": transaction["pk"], "status": "processed"}


@tracer.capture_method
def record_handler(record: SQSRecord):
    envelope = json.loads(record.body)      # il messaggio SQS contiene l'evento EventBridge completo
    return process_transaction(transaction=envelope["detail"])


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event, context):
    idempotency_config.register_lambda_context(context)
    return process_partial_response(
        event=event, record_handler=record_handler, processor=processor, context=context,
    )