"""HTTP API Lambda: routes requests from API Gateway (HTTP API, payload v2)."""

from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

from flatsplit_api.models import HealthResponse

logger = Logger()

# CloudFront forwards browser requests as /api/...; local Vite strips the prefix.
app = APIGatewayHttpResolver(strip_prefixes=["/api"], enable_validation=True)


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse()


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(event, context)
