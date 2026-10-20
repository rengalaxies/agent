"""Loopback product server with operator-owned bindings and bearer identities."""
import argparse
import os

from .delivery import DeliveryConfig, GatewayDelivery
from .models import TransitionSpec
from .run_cli import operator_path, read_operator_file
from .store import RunStore
from .verification import TrustPolicy, load_json
from .verify_cli import TrustConfig
from .adapters import read_repository_file
from .web_api import create_product_app
from .workflow_service import Principal, WorkflowService
from .workflow_store import WorkflowStore

PERMISSIONS = frozenset({"read", "review", "prepare_delivery", "send_delivery", "tick", "revalidate"})


def bind_service(repository, transition, expectations, fixtures, trust, state, *, worker_actor,
                 delivery=None):
    repository, state = operator_path(repository), operator_path(state)
    if state.resolve().is_relative_to(repository.resolve()):
        raise ValueError("state inside repository")
    for value in (transition, expectations, fixtures, trust):
        if operator_path(value).resolve().is_relative_to(repository.resolve()):
            raise ValueError("control artifact inside repository")
    def policy():
        config = TrustConfig.model_validate(load_json(read_operator_file(trust)))
        return TrustPolicy(**{k: getattr(config, k) for k in TrustConfig.model_fields})
    gateway, destinations, notifications = None, {}, {}
    if delivery:
        if operator_path(delivery).resolve().is_relative_to(repository.resolve()):
            raise ValueError("delivery config inside repository")
        data = load_json(read_operator_file(delivery))
        if not set(data) <= {"config", "repositories", "notifications"}:
            raise ValueError("invalid delivery configuration")
        config = data.get("config", {})
        env = config.pop("key_env", None)
        if "api_key" in config:
            raise ValueError("use key_env rather than inline secret")
        if env:
            config["api_key"] = os.environ[env]
        config["allowed_endpoints"] = frozenset(config.get("allowed_endpoints", []))
        if any(type(config.get(k, False)) is not bool for k in ("allow_send", "allow_loopback_http")):
            raise ValueError("delivery flags must be boolean")
        gateway = GatewayDelivery(DeliveryConfig(**config))
        destinations, notifications = data.get("repositories", {}), data.get("notifications", {})
    return WorkflowService(RunStore(state / "runs.sqlite3"), WorkflowStore(state / "workflow.sqlite3"), repository,
                           lambda: TransitionSpec.model_validate(load_json(read_operator_file(transition))),
                           lambda: read_operator_file(expectations),
                           lambda uri: read_repository_file(operator_path(fixtures), uri), policy,
                           worker_actor=worker_actor, gateway=gateway,
                           destinations=destinations, notification_routes=notifications)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("repository", "transition", "expectations", "fixtures", "trust", "state", "identities", "worker-actor"):
        parser.add_argument("--"+key, required=True)
    parser.add_argument("--delivery-config")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)
    service = bind_service(args.repository, args.transition, args.expectations, args.fixtures,
                           args.trust, args.state, worker_actor=args.worker_actor, delivery=args.delivery_config)
    if operator_path(args.identities).resolve().is_relative_to(operator_path(args.repository).resolve()):
        raise ValueError("identities inside candidate repository")
    data = load_json(read_operator_file(args.identities))
    identities = {}
    for item in data["identities"]:
        permissions = frozenset(item["permissions"])
        if not permissions <= PERMISSIONS:
            raise ValueError("unknown permission")
        token = os.environ[item["token_env"]]
        if token in identities or len(token) < 32:
            raise ValueError("duplicate or weak identity")
        identities[token] = Principal(item["actor"], frozenset(item["transitions"]), permissions)
    import uvicorn
    uvicorn.run(create_product_app(service, identities), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
