import json
import os
import uuid
from datetime import datetime, timezone

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def handler(event, context):
    item = {"pk": str(uuid.uuid4()), "createdAt": datetime.now(timezone.utc).isoformat()}
    table.put_item(Item=item)
    return {"statusCode": 200, "body": json.dumps(item)}