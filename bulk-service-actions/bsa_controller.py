#!/usr/bin/env python3
"""
This is the Bulk Service Actions (BSA) controller script, used for interacting with the
actions in the package bulk-service-actions.

The actions in general can be interacted with directly as well, but this script makes it
a bit easier when working with a lot of services at once since it accepts an input file
of keypaths and also shorter, more human-friendly names. It also presents the dry-run
output in a more readable fashion and adds some basic quality of life inputs to some of
the common tasks. The options are mostly self explanatory but there are also some usage
examples and a brief overview in the README.md file in the bulk-service-actions
package.
"""
import json
import re
import textwrap
import time as epoch_time
import os
import sys
from typing import List, Union, Dict
import click
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def require_env(variables) -> None:
    """
    Checks required environment variables
    """
    env = os.environ

    missing = [x for x in variables if x not in env or env[x].strip() == ""]

    if missing:
        print("The bsa-controller requires these environment variables to be set:")

        for x in variables:
            if x in missing:
                print(f"[ ] {x}")
            else:
                print(f"[x] {x}")

        print(
            "\nNSO_URL should be in URL format with port, e.g.: https://127.0.0.1:8080"
        )

        sys.exit(1)


require_env(["NSO_URL", "NSO_API_USER", "NSO_API_PASSWORD"])

API_USER = os.environ.get("NSO_API_USER")
API_PASSWORD = os.environ.get("NSO_API_PASSWORD")
NSO_URL = os.environ.get("NSO_URL")


class ControllerRun:
    """ControllerRun Class"""

    def __init__(self, service_ids=None, input_file=None):
        self.provided_services = False
        if any([service_ids, input_file]):
            self.provided_services = True
        self.service_paths = build_service_paths(service_ids, input_file)
        self.service_list = send_request("get", "services")


@click.group()
@click.option(
    "-s",
    "--service-ids",
    "service_ids",
    help="Provide comma-separated list of services",
)
@click.option(
    "-f",
    "--input-file",
    "input_file",
    help="Read services from file, one per line",
)
@click.pass_context
def cli(ctx: ControllerRun, service_ids: str, input_file: str):
    """
    Controller program for NSO bulk service actions

    Identify services either with keypath or in <service-type>::<service-id> format
    """
    ctx.obj = ControllerRun(service_ids, input_file)


# Utility functions
def send_request(
    method: str, suffix: str, body=None, datastore: str = "data"
) -> requests.Response:
    """
    Reusable request function for fetching/posting data
    """
    root = f"/restconf/{datastore}/bulk-service-actions:bulk-service-actions/"
    headers = {
        "Accept": "application/yang-data+json",
        "Content-Type": "application/yang-data+json",
    }
    url = f"{NSO_URL}{root}{suffix}"
    call = {
        "put": requests.put,
        "post": requests.post,
        "get": requests.get,
        "patch": requests.patch,
    }
    response = call[method](
        url, auth=(API_USER, API_PASSWORD), verify=False, headers=headers, json=body
    )
    if response.status_code == 204 and method == "get":
        raise ValueError(
            "/bulk-service-actions/services is empty, "
            "please generate the service-list first"
        )
    return response


def create_keypath(service_id: str) -> str:
    """
    Takes either <service-type>::<service-id> or keypath and returns keypath (unchanged
    if given keypath)
    """
    assert "::" in service_id or re.match(
        "^\\/", service_id
    ), "Please provide keypath or service-id in format <service_type>::<service_id>"

    if re.match("^\\/", service_id):
        return service_id

    service_type = service_id.split("::")[0]
    service_id = service_id.split("::")[1]
    service_types = [
        "5g-mbh",
        "cfs-l2-p2p",
        "cfs-mp-2-mp",
        "sync-device",
        "sync-endpoint",
    ]
    assert service_type in service_types, f"Service type must be one of {service_types}"
    bespoke = "/ncs:services/struct:bespoke"
    network = "/ncs:services/struct:network"
    prefixes = {
        "5g-mbh": f"{bespoke}/mobile-backhaul:mbh/service",
        "cfs-l2-p2p": f"{bespoke}/cfs-l2-p2p:cfs-l2-p2p/service",
        "cfs-mp-2-mp": f"{bespoke}/cfs-l2-p2p:cfs-mp-2-mp/service",
        "sync-device": f"{network}/cfs-network-sync:network-sync/device",
        "sync-endpoint": f"{network}/cfs-network-sync:network-sync/endpoint",
    }
    keypath = f"{prefixes[service_type]}{{{service_id}}}"

    return keypath


def parse_service_ids(service_ids: Union[str, List]) -> List:
    """
    Helper function to output a list of keypaths given either service IDs or keypaths
    """
    if isinstance(service_ids, str):
        service_ids = service_ids.split(",")
    return [create_keypath(service_id) for service_id in service_ids]


def build_service_paths(
    service_ids: Union[None, str], input_file: Union[None, str]
) -> List:
    """
    Helper function to build a list of services to interact with based on inputs
    """
    if any([service_ids, input_file]):
        if service_ids is not None:
            return parse_service_ids(service_ids)
        if input_file is not None:
            with open(f"{input_file}", encoding="utf-8") as file:
                service_ids = file.read().splitlines()
                return parse_service_ids(service_ids)
    return []


# Commands
@cli.command()
@click.argument(
    "display-item",
    required=False,
    type=click.Choice(["dry-run", "modified-services", "errors"]),
)
@click.option(
    "-F",
    "--filter",
    "output_filter",
    type=click.Choice(["redeploy-ready", "no-redeploy-ready", "last-redeploy-error"]),
    help="Display only services matching a condition",
)
@click.pass_context
def display(  # pylint: disable=too-many-statements
    ctx: ControllerRun, display_item: str = None, output_filter: str = None
) -> None:
    """
    Display various attributes of the service-list
    """
    click.echo("\n")
    common = ctx.obj
    service_paths = common.service_paths
    provided_services = common.provided_services
    service_list = json.loads(common.service_list.content)

    if "bulk-service-actions:services" not in service_list:
        raise ValueError(f"Malformed response from server. Got: {service_list}")

    def _print_keypath(keypath) -> None:
        """
        Helper function to print the keypath where desired
        """
        click.secho(keypath, fg="white")

    def _display_modified_services(service: Dict[str, str]) -> None:
        """
        Helper function to display modified-services, called from _display_handler()
        """
        if "modified-services" in service:
            _print_keypath(service["keypath"])
            click.secho("  +- modified services:", fg="magenta")
            for modified_service in service["modified-services"]:
                service_block = modified_service["keypath"].split("/")[4]
                service = re.search(":(.*){", service_block).group(1)
                keys = re.search("{(.*)}", modified_service["keypath"]).group(1)
                key_list = keys.split()[:-1]
                key_string = " ".join(str(key) for key in key_list)
                click.secho(f"    +- {service} {key_string}", fg="bright_magenta")
                if "dry-run" in modified_service:
                    _display_dry_run(
                        modified_service, indent="      ", supress_keypath=True
                    )
                if "redeployed-at" in modified_service:
                    click.secho(
                        f"      +- redeployed at: {modified_service['redeployed-at']}",
                        fg="cyan",
                    )
            click.echo("")

    def _display_errors(service: Dict[str, str]) -> None:
        """
        Helper function to display errors, called from _display_handler()
        """
        if "last-redeploy-error" in service:
            _print_keypath(service["keypath"])
            click.secho(
                f"  +- last redeploy error: \"{service['last-redeploy-error']}\"",
                fg="red",
            )
            click.echo("")

    def _display_dry_run(
        service: Dict[str, str], indent: str = "  ", supress_keypath: bool = False
    ) -> None:
        """
        Helper function to display dry-run, called from _display_handler()
        """
        if "dry-run" in service:
            if "output" in service["dry-run"]:
                if supress_keypath is False:
                    _print_keypath(service["keypath"])
                click.secho(f"{indent}+- dry-run", fg="cyan")
                click.secho(f"{indent}  +- fetched at ", fg="cyan", nl=False)
                click.secho(
                    f"{service['dry-run']['fetched-at']}",
                    fg="yellow",
                )
                click.secho(
                    f"{indent}  +- output",
                    fg="cyan",
                )
                for device in service["dry-run"]["output"]:
                    click.secho(
                        f"{indent}    +- {device['device']}:", fg="red", bold=True
                    )
                    click.secho(
                        f"{textwrap.indent(device['output'], f'{indent}      ')}",
                        fg="bright_blue",
                    )
            elif "last-redeploy-error" in service:
                click.secho(
                    f"{indent}  +- no diff: \"{service['last-redeploy-error']}\"",
                    fg="red",
                )
                click.echo("")
            else:
                if output_filter != "diff-only":
                    if supress_keypath is False:
                        _print_keypath(service["keypath"])
                    click.secho(f"{indent}+- dry-run", fg="cyan")
                    click.secho(f"{indent}  +- fetched at ", fg="cyan", nl=False)
                    click.secho(
                        f"{service['dry-run']['fetched-at']}",
                        fg="yellow",
                    )
                    click.secho(
                        f"{indent}  +- no diff",
                        fg="green",
                        bold=True,
                    )
                    click.echo("")
        else:
            if provided_services:
                if supress_keypath is False:
                    _print_keypath(service["keypath"])
                click.secho(
                    f"{indent}  +- no dry-run output, has a dry-run been performed?",
                    fg="red",
                )
                click.echo("")

    def _display_determiner(service: str) -> bool:
        """
        Determine whether or not to display this item
        """
        if output_filter == "diff-only" and "" in service:
            return True

        if output_filter == "last-redeploy-error" and "last-redeploy-error" in service:
            return True

        if output_filter == "redeploy-ready" and "redeploy-ready" in service:
            return True

        if output_filter == "no-redeploy-ready" and "redeploy-ready" not in service:
            return True

        if output_filter is None:
            return True

        return False

    def _display_handler(service: str) -> None:
        """
        Main display handler function
        """
        if _display_determiner(service):
            if display_item is None:
                _print_keypath(service["keypath"])
                if "redeploy-ready" in service:
                    click.secho("  +- service is ready for redeploy!", fg="bright_cyan")
                if "redeployed-at" in service:
                    click.secho(
                        f"  +- redeployed at: {service['redeployed-at']}", fg="cyan"
                    )
            if display_item == "dry-run":
                _display_dry_run(service)
            if display_item == "modified-services":
                _display_modified_services(service)
            if display_item == "errors":
                _display_errors(service)
            if display_item is None and output_filter is None:
                click.echo("")

    # Main function clause which calls _display_handler()
    if service_paths == []:
        for service in service_list["bulk-service-actions:services"]:
            _display_handler(service)
    else:
        for service in service_list["bulk-service-actions:services"]:
            if service["keypath"] in service_paths:
                _display_handler(service)


@cli.command()
@click.pass_context
def approve_diff(ctx: ControllerRun) -> None:
    """
    Approve the dry-run diff of a given service
    """
    common = ctx.obj
    service_paths = common.service_paths
    assert len(service_paths) == 1, "Approve diff command requires exactly one service"
    service = service_paths[0]
    suffix = "service-list-tools"
    json_input = {"diff-approval": {"approve-diff": service}}
    json_dump = json.dumps(json_input)
    json_object = json.loads(json_dump)

    result = send_request("post", suffix, json_object)
    if result.status_code != 204:
        raise ValueError(f"Request failed with {result.status_code}")

    click.secho(
        f"Dry-run from {service} added to approved-diffs list!",
        fg="green",
        bold=True,
    )


@cli.command()
@click.pass_context
@click.argument(
    "action",
    required=True,
    type=click.Choice(["mark-as-ready", "mark-as-unready", "clear"]),
)
def edit_service_list(ctx: ControllerRun, action: str) -> None:
    """
    Interact with services in the list
    """
    common = ctx.obj
    service_paths = common.service_paths
    suffix = "service-list-tools"
    if service_paths == []:
        targets = {"all": [None]}
    else:
        targets = {"keypath": service_paths}
    if action == "mark-as-ready":
        json_input = {"redeploy-ready": {"operation": "add", "targets": targets}}
    if action == "mark-as-unready":
        json_input = {"redeploy-ready": {"operation": "remove", "targets": targets}}
    if action == "clear":
        json_input = {"clear": {"targets": targets}}
    json_dump = json.dumps(json_input)
    json_object = json.loads(json_dump)

    result = send_request("post", suffix, json_object)
    if result.status_code != 204:
        raise ValueError(f"Request failed with {result.status_code}")

    if action == "mark-as-ready":
        click.secho(
            f"Services {targets} marked as redeploy-ready!",
            fg="green",
            bold=True,
        )
    elif action == "clear":
        click.secho(
            f"Services {targets} cleared from service list!",
            fg="green",
            bold=True,
        )


@cli.command()
@click.option(
    "-t", "--time", help="Schedule time for activity", required=False, default=None
)
@click.option(
    "-i",
    "--interval",
    help="Interval in seconds between actions",
    required=False,
    default=30,
)
@click.option(
    "-a",
    "--action",
    help="Action type: redeploy-top-level or reconcile-sublayers",
    required=False,
    type=click.Choice(["redeploy-top-level", "reconcile-sublayers"]),
    default="redeploy-top-level",
)
@click.option(
    "--dry-run-false",
    help="Schedule a non-dry-run action",
    required=False,
    is_flag=True,
)
@click.option(
    "--no-networking",
    help="Schedule a no-networking action",
    required=False,
    is_flag=True,
)
@click.option(
    "-S",
    "--subset-of-all",
    help="Target subset of services",
    required=False,
    type=click.Choice(
        [
            "last-redeploy-error",
            "no-dry-run-diff",
            "no-dry-run-fetched-at",
            "no-redeployed-at",
            "redeploy-ready",
            "redeployed-at",
        ]
    ),
)
@click.pass_context
def schedule_redeploy(
    ctx: ControllerRun,
    dry_run_false: bool,
    no_networking: bool,
    time: str = None,
    interval: int = 30,
    action: str = "redeploy-top-level",
    subset_of_all: str = None,
) -> None:
    """
    Schedule a redeploy/reconcile activity

    Time: scheduled time in either ISO format (YYYY-MM-DDTHH:MM:SS) or time from now in
    the format of, e.g. 6h15m for 6 hours and 15 minutes from now, if not given
    it is scheduled immediately. Note: Offset minutes must be given, even if 00!

    !NOTE! The default immediate schedule will not work accurately if the target server
    has different time than where the script is being run from. In such cases supply a
    time slightly in the future of local server time.
    """
    common = ctx.obj
    service_paths = common.service_paths
    dry_run = "true"
    no_networking = "false"
    if dry_run_false:
        dry_run = "false"
    if no_networking:
        no_networking = "true"

    if subset_of_all is not None and service_paths != []:
        click.secho(
            "subset-of-all cannot be given with explicit service list, exiting!",
            fg="red",
            bold=True,
        )
        return
    # schedule to 1 minute from now if time is not set
    if time is None:
        schedule = {"in-time": "00h01m"}
        message = "1 minute from now"
    # schedule to given time if supplied time is ISO
    elif re.match("^\\d{4}-\\d{2}-\\d{2}", time):
        schedule = {"at-time": time}
        message = time
    # schedule relative if supplied time is offset
    else:
        schedule = {"in-time": time}
        message = f"in {time} from now"

    if not click.confirm(
        f"Scheduling a {action} action with dry-run {dry_run} and "
        f"no-networking {no_networking} for {message}. Confirm?"
    ):
        click.secho(
            "Canceling!",
            fg="red",
            bold=True,
        )
        return
    suffix = "activity"

    epoch = re.match("^(.*)\\.", str(epoch_time.time())).group(1)
    activity_name = f"bsa-controller_{action}_{epoch}"

    if subset_of_all is not None:
        targets = {"subset-of-all": {subset_of_all: [None]}}
    elif service_paths == []:
        targets = {"all": [None]}
    else:
        targets = {"keypath": service_paths}

    service_def = {
        "bulk-service-actions:activity": [
            {
                "name": activity_name,
                "action": {action: [None]},
                "targets": targets,
                "commit-flags": {
                    "dry-run": dry_run,
                    "no-networking": no_networking,
                },
                "interval": interval,
                "schedule": schedule,
            }
        ]
    }
    service_def_dump = json.dumps(service_def)
    service_def_object = json.loads(service_def_dump)

    result = send_request("patch", suffix, service_def_object)
    if result.status_code != 204:
        raise ValueError(f"Request failed with {result.status_code}: {result.content}")

    click.secho(
        f"Activity {activity_name} scheduled! See /bulk-service-actions/activity "
        "for details",
        fg="green",
        bold=True,
    )


if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
