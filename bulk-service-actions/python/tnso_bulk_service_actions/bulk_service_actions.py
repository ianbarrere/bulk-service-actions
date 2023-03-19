# -*- mode: python; python-indent: 4 -*-
""" Implementation of Services and Actions """
from typing import Dict, Set, cast, Literal
import re
import datetime
import ncs
from ncs.application import Service
from ncs.dp import Action
import _ncs

PropList = List[Tuple[str, str]]

def str_to_bool(bool_str: str) -> bool:
    """
    Used for converting string boolean values like "true" used inside NSO to actual
    booleans
    """
    if bool_str.casefold() == "true":
        return True

    return False


def parse_dry_run(dry_run: str) -> str:
    """
    Simple function to format dry-run output
    Currently only swaps out wildcards, could be expanded to do more
    """
    with ncs.maapi.single_read_trans(
        user="admin", context="system", groups=["system"]
    ) as transaction:
        root = ncs.maagic.get_root(transaction)
        wildcards = root.bulk_service_actions.settings.diff_checking.wildcard
        return_output = dry_run
        if len(wildcards) > 0:
            for index, wildcard in enumerate(wildcards):
                return_output = re.sub(
                    rf"{wildcard}", f"*WILDCARD{index+1}*", return_output
                )

        return return_output


def build_service_set(node: ncs.maagic.Node) -> Set[str]:
    """
    Shared logic tree for building set of services to act on:

    Node has 'all' and/or 'keypath' defined.
    - If keypath is given only, keypath is treated as include
    - If keypath and all is given, keypath is treated as exclude
    - If all is given only, list of all keypaths is returned

    subset-of-all gives the user the ability to select all services with a particular
    flag
    """

    def should_include_service(
        service: ncs.maagic.Node, subset: ncs.maagic.Container
    ) -> bool:
        """helper function to include desired subsets of services"""
        if subset.last_redeploy_error and service.last_redeploy_error:
            return True

        if subset.no_dry_run_diff and len(service.dry_run.output) == 0:
            return True

        if subset.no_dry_run_fetched_at and not service.dry_run.fetched_at:
            return True

        if subset.no_redeployed_at and not service.redeployed_at:
            return True

        if subset.redeployed_at and service.redeployed_at:
            return True

        if subset.redeploy_ready and service.redeploy_ready:
            return True

        return False

    with ncs.maapi.single_read_trans(
        user="admin", context="system", groups=["system"]
    ) as transaction:
        root = ncs.maagic.get_root(transaction)

        if len(root.bulk_service_actions.services) == 0:
            raise AttributeError("Please run service-list populate action first!")

        all_services = set(
            service.keypath for service in root.bulk_service_actions.services
        )

        # if no targets specified then act on all
        if not node.targets:
            return all_services

        if node.targets.all:
            # if subset-of-all then return desired subset
            if node.targets.all.subset:
                subset = node.targets.all.subset
                return set(
                    service.keypath
                    for service in root.bulk_service_actions.services
                    if should_include_service(service, subset)
                )
            if node.targets.keypath:
                # branch for keypath as exclude
                return set(all_services) - set(list(node.targets.keypath))
            # branch for all
            return all_services

        # branch for keypath as include
        return set(list(node.targets.keypath))


def able_to_redeploy(
    dry_run: bool,
    service: ncs.maagic.Node,
    calling_class: Literal["ResolveTopLevel", "ReconcileSublayers"],
) -> bool:
    """Helper function to determine if the requested service can be redeployed"""
    if not dry_run:
        if service.redeploy_ready:
            return True
        if calling_class == "ReconcileSublayers" and service.redeployed_at:
            return True

        return False

    return True


def redeploy(
    node: ncs.maagic.Node,
    service: ncs.maagic.Node,
    commit_flags: Dict[str, bool],
    output: Set[str],
    approved_diffs: ncs.maagic.List = None,
) -> Set[str]:
    """
    Shared redeploy function for redeploy-top-level and reconcile-sublayers. It's a bit
    ugly since it needs to accommodate a variety of behaviors while using the maagic
    objects of the required nodes.

    Args:
        node: Maagic node of service to redeploy/reconcile
        service: Entry in /bulk-service-actions/services(/modified-services) for service
        approved_diffs:
        commit_flags: dict of boolean commit flags
        output: Set of output parameters
        approved_diffs: Object containing the approved diffs configured
    Returns:
        Output set
    """

    def _dry_run_true(service: ncs.maagic.Node) -> None:
        """Non reconcile dry-run method"""

        # clear flags from previous run
        if service.redeploy_ready:
            del service.redeploy_ready
        if service.last_redeploy_error:
            del service.last_redeploy_error
        # if no diff mark as redeploy ready
        if len(result.native.device) == 0:
            service.redeploy_ready.create()
        # if all diffs are already approved mark as redeploy ready
        if approved_diffs is not None and all(
            (device.data in approved_diffs) for device in result.native.device
        ):
            service.redeploy_ready.create()

    def _dry_run_true_common(service: ncs.maagic.Node) -> None:
        """Dry-run operations common to reconcile and non-reconcile"""

        # populate/overwrite dry-run output in service list
        if service.dry_run:
            del service.dry_run
        # delete redeployed-at flag from previous non dry-run execution
        if service.redeployed_at:
            del service.redeployed_at
        service.dry_run.create()
        service.dry_run.fetched_at = time_now
        for device in result.native.device:
            service.dry_run.output.create(device.name)
            service.dry_run.output[device.name].output = parse_dry_run(device.data)

    def _dry_run_false(service: ncs.maagic.Node) -> None:
        """Non dry-run method"""

        service.redeployed_at = time_now
        if service.last_redeploy_error:
            del service.last_redeploy_error
        if service.dry_run:
            del service.dry_run
        if not commit_flags["reconcile"]:
            del service.redeploy_ready

    def _set_inputs(node: ncs.maagic.Node) -> ncs.maagic.ActionParams:
        """Set inputs method"""
        service_redeploy = node.re_deploy
        inputs = cast(ncs.maagic.ActionParams, service_redeploy.get_input())
        if commit_flags["dry-run"]:
            inputs.dry_run.create()
            inputs.dry_run.outformat = "native"
        if commit_flags["reconcile"]:
            inputs.reconcile.create()
        if commit_flags["no-networking"]:
            inputs.no_networking.create()
        return inputs

    time_now = datetime.datetime.now().isoformat()

    # create redeploy inputs
    inputs = _set_inputs(node)

    # main try-except clause for redeploy or marking error in services list
    try:
        result = node.re_deploy(inputs)
        # dry-run true
        if commit_flags["dry-run"]:
            if commit_flags["reconcile"]:
                _dry_run_true(service)
            _dry_run_true_common(service)
        # dry-run false
        else:
            _dry_run_false(service)
    except _ncs.error.Error as error:
        service.last_redeploy_error = error
        output.add("There were errors during one or more redeploys")

    return output


class BulkServiceActionScheduler(Service):
    """
    Servicepoint for action scheduler. Can schedule either a top-level redeploy or a
    sublayer reconciliation.
    """

    @Service.create
    def cb_create(
        self,
        transaction: _ncs.TransCtxRef,
        root: ncs.maagic.Root,
        service: ncs.maagic.ListElement,
        proplist: PropList,
    ) -> None:
        """NSO create Callback"""

        if service.action.redeploy_top_level:
            action_name = "redeploy-top-level"
        if service.action.reconcile_sublayers:
            action_name = "reconcile-sublayers"

        schedule = service.schedule
        if any([schedule.at_time, schedule.in_time]):
            time_now = datetime.datetime.fromisoformat(
                datetime.datetime.now().isoformat()
            )
            if schedule.at_time:
                schedule_time = datetime.datetime.fromisoformat(schedule.at_time)
            if schedule.in_time:
                hours_re = re.search("(\\d+)h", schedule.in_time)
                assert hours_re is not None
                hours = int(hours_re.group(1))
                minute_re = re.search("(\\d+)m", schedule.in_time)
                assert minute_re is not None
                minutes = int(minute_re.group(1))
                schedule_time = time_now + datetime.timedelta(
                    hours=hours, minutes=minutes
                )

            if schedule_time < time_now:
                raise ValueError("Please specify a scheduled time in the future")
            for index, to_schedule in enumerate(build_service_set(service)):
                dry_run = str(service.commit_flags.dry_run).lower()
                no_networking = str(service.commit_flags.no_networking).lower()
                xml_params = f"""<commit-flags>
                                    <dry-run>{dry_run}</dry-run>
                                    <no-networking>{no_networking}</no-networking>
                                </commit-flags>
                                <targets>
                                    <keypath>{to_schedule}</keypath>
                                </targets>"""
                delay_seconds = index * service.interval
                task = root.scheduler.task.create(
                    f"bulk-service-action-scheduler_{action_name}_{to_schedule}"
                )
                task.action_name = f"{action_name}"
                task.action_node = "/bulk-service-actions"
                task.action_params = xml_params
                task.time = datetime.datetime.isoformat(
                    schedule_time + datetime.timedelta(seconds=int(delay_seconds))
                )


class BulkServiceActionServiceListService(Service):
    """
    Servicepoint for list clearing after settings change
    Deletes current operational data list in case of change
    """

    @Service.create
    def cb_create(
        self,
        transaction: _ncs.TransCtxRef,
        root: ncs.maagic.Root,
        service: ncs.maagic.ListElement,
        proplist: PropList,
    ) -> None:
        """NSO create Callback"""
        self.log.info(
            "Service settings changed, clearing operational data from "
            "/bulk-service-actions/services"
        )
        del root.bulk_service_actions.services


class ServiceList(Action):
    """
    Actionpoint for service list interaction. Input to either populate or prune.
    This will loop through the predefined set of top-level services and populate
    /bulk-service-actions/services and will then determine modified services of those
    top-level services and populates them under
    /bulk-service-actions/services/modified-services
    """

    @Action.action
    def cb_action(
        self,
        uinfo: _ncs.UserInfo,
        name: str,
        keypath: _ncs.HKeypathRef,
        action_input: ncs.maagic.Node,
        action_output: ncs.maagic.Node,
        caller_transaction: ncs.maapi.Transaction,
    ) -> None:
        _ncs.dp.action_set_timeout(uinfo.user_info, 1200)
        self.log.info(f"Action {name}")
        if action_input.populate:
            action_output.output = self.populate()
        if action_input.clear:
            action_output.output = self.clear(action_input)

    def clear(self, action_input: ncs.maagic.Node) -> str:
        """
        Function to clear elements from the service list
        """
        with ncs.maapi.start_write_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)
            clear_set = build_service_set(action_input.clear)
            # normal deletion through _clear() doesn't seem to work, so this is a
            # crude workaround to delete the whole list if the lengths are equal
            if len(clear_set) == len(root.bulk_service_actions.services):
                del root.bulk_service_actions.services
                return f"Cleared services {clear_set} from service list"

            for to_clear in clear_set:
                del root.bulk_service_actions.services[to_clear]
            self.log.info(f"Cleared {clear_set} from service list")

            transaction.apply()

        return f"Cleared services {clear_set} from service list"

    def populate(self) -> str:
        """
        Function to populate the service list
        """
        with ncs.maapi.single_read_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)

            # Service types fetched from settings in following format, e.g.
            # /services/path/to/my/service
            paths = root.bulk_service_actions.settings.service_list.top_level_types
            if len(paths) == 0:
                return (
                    "ERROR: No services defined at /bulk-service-actions/settings/"
                    "service-list/top-level-types"
                )

            service_list = [
                service._path
                for path in paths
                for service in ncs.maagic.get_node(root, path)
            ]

        with ncs.maapi.start_write_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)
            settings = root.bulk_service_actions.settings
            for service in service_list:
                # create main list entry
                action_services = root.bulk_service_actions.services
                action_services.create(service)

                # populate modified service list
                service_node = ncs.maagic.get_node(root, service)
                try:
                    modified_services = service_node.modified.services
                    target_sublayers = settings.service_list.target_sublayers
                    services_to_reconcile = [
                        str(modified_service)
                        for modified_service in modified_services
                        if any(
                            target in str(modified_service)
                            for target in target_sublayers
                        )
                    ]
                # if attempting to show the service operational data on the CLI gives
                # "internal error" then we get python error "Transaction not found (61)"
                # a redeploy of the CFS usually fixes this
                except _ncs.error.Error:
                    services_to_reconcile = [
                        "Service operational data corrupt, please redeploy CFS first"
                    ]
                for service_to_reconcile in services_to_reconcile:
                    action_services[service].modified_services.create(
                        service_to_reconcile
                    )

            transaction.apply()

        self.log.info("Populated service-list at /bulk-service-actions/services")
        return "See /bulk-service-actions/services for service list"


class RedeployTopLevel(Action):
    """
    Actionpoint for top-level service redeploy
    """

    @Action.action
    def cb_action(
        self,
        uinfo: _ncs.UserInfo,
        name: str,
        keypath: _ncs.HKeypathRef,
        action_input: ncs.maagic.Node,
        action_output: ncs.maagic.Node,
        caller_transaction: ncs.maapi.Transaction,
    ) -> None:
        # set action timeout to 20 minutes to allow for bulk processing services
        _ncs.dp.action_set_timeout(uinfo.user_info, 1200)
        self.log.info(f"Action {name}")

        # Get list of services to redeploy from inputs
        change_set = build_service_set(action_input)

        # Define output as set which can be appended to for different branches below
        output = set()
        output.add(
            "redeploy-top-level action called with dry-run "
            f"{action_input.commit_flags.dry_run} and no-networking "
            f"{action_input.commit_flags.no_networking} for service(s) {change_set}"
        )

        with ncs.maapi.start_write_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)
            output.add("See /bulk-service-actions/services for output")
            if len(root.bulk_service_actions.services) == 0:
                output = set("Please run populate-service-list action first!")

            commit_flags = {
                "dry-run": str_to_bool(action_input.commit_flags.dry_run),
                "no-networking": str_to_bool(action_input.commit_flags.no_networking),
                "reconcile": False,
            }

            approved_diffs = root.bulk_service_actions.approved_diffs
            for to_change in change_set:
                service = root.bulk_service_actions.services[to_change]
                node = ncs.maagic.get_node(root, service.keypath)
                # skip services not ready for redeploy
                if not able_to_redeploy(commit_flags["dry-run"], service, self.__class__.__name__):
                    service.last_redeploy_error = (
                        f"Service {service.keypath} not "
                        "flagged as redeploy-ready, skipping"
                    )
                    output.add("Redeploy-ready not set for one or more services")
                    continue

                output = redeploy(node, service, commit_flags, output, approved_diffs)

            transaction.apply()
            self.log.info(f"Action {name} - output: {output}")
            action_output.output = output


class ReconcileSublayers(Action):
    """
    Actionpoint for sublayer reconciliation. A particular top-level service is given and
    the sublayer services specified under settings are reconciled.
    """

    @Action.action
    def cb_action(
        self,
        uinfo: _ncs.UserInfo,
        name: str,
        keypath: _ncs.HKeypathRef,
        action_input: ncs.maagic.Node,
        action_output: ncs.maagic.Node,
        caller_transaction: ncs.maapi.Transaction,
    ) -> None:
        # set action timeout to 20 minutes to allow for bulk processing services
        _ncs.dp.action_set_timeout(uinfo.user_info, 1200)
        self.log.info(f"Action {name}")

        # Get list of services to redeploy from inputs
        change_set = build_service_set(action_input)
        # Define output as set which can be appended to for different branches below
        output = set()
        output.add(
            "reconcile-sublayers action called with dry-run "
            f"{action_input.commit_flags.dry_run} and no-networking "
            f"{action_input.commit_flags.no_networking} for service(s) {change_set}"
        )

        with ncs.maapi.start_write_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)
            commit_flags = {
                "dry-run": str_to_bool(action_input.commit_flags.dry_run),
                "no-networking": str_to_bool(action_input.commit_flags.no_networking),
                "reconcile": True,
            }
            for to_change in change_set:
                service = root.bulk_service_actions.services[to_change]
                for modified_service in service.modified_services:
                    # skip services not ready for redeploy
                    class_name = self.__class__.__name__
                    if not able_to_redeploy(commit_flags["dry-run"], service, class_name):
                        modified_service.last_redeploy_error = (
                            f"Service {service.keypath} not "
                            "flagged as redeploy-ready or not yet redeployed, skipping"
                        )
                        output.add("Redeploy-ready not set for one or more services")
                        continue
                    node = ncs.maagic.get_node(root, modified_service.keypath)
                    output = redeploy(node, modified_service, commit_flags, output)

            transaction.apply()
            self.log.info(f"Action {name} - output: {output}")
            action_output.output = output


class ServiceListTools(Action):
    """
    Actionpoint for operational data update tool. This allows you to set the
    redeploy-ready flag for services that have been verified and approve diffs
    """

    @Action.action
    def cb_action(
        self,
        uinfo: _ncs.UserInfo,
        name: str,
        keypath: _ncs.HKeypathRef,
        action_input: ncs.maagic.Node,
        action_output: ncs.maagic.Node,
        caller_transaction: ncs.maapi.Transaction,
    ) -> None:
        self.log.info(f"Action {name}")

        def _redeploy_ready(inputs: ncs.maagic.Node, services: ncs.maagic.Node) -> None:
            """
            Adds redeploy-ready flag to given services
            """
            change_set = build_service_set(inputs)
            for to_change in change_set:
                if inputs.operation == "add":
                    services[to_change].redeploy_ready.create()
                else:
                    if services[to_change].redeploy_ready:
                        del services[to_change].redeploy_ready
            self.log.info(f"Marking {change_set} as redeploy-ready")

        def _diff_approval(
            inputs: ncs.maagic.Node,
            services: ncs.maagic.Node,
            approved_diffs: ncs.maagic.Node,
        ) -> None:
            """
            Handles approving diffs of services
            """
            # approve a single diff
            if inputs.approve_diff:
                target = action_input.diff_approval.approve_diff
                if len(services[target].dry_run.output) == 0:
                    self.log.info(f"{target} has no diff, skipping")
                for device in services[target].dry_run.output:
                    self.log.info(f"Adding {device.output} to approved-diffs")
                    approved_diffs.create(parse_dry_run(device.output))
            # crosscheck all existing diffs with approved diffs
            if inputs.check_approvals:
                for service in services:
                    if len(service.dry_run.output) > 0:
                        if all(
                            (device.output in approved_diffs)
                            for device in service.dry_run.output
                        ):
                            self.log.info(
                                f"Marking {service.keypath} as redeploy-ready"
                            )
                            service.redeploy_ready.create()

        def _wildcards(
            inputs: ncs.maagic.Node,
            services: ncs.maagic.Node,
            approved_diffs: ncs.maagic.Node,
        ) -> None:
            """
            Allows for updating and rolling back diff wildcards
            """
            if inputs.operation == "update":
                self.log.info("Updating wildcards in dry-runs and approved diffs")
                for approved_diff in approved_diffs:
                    if parse_dry_run(approved_diff.diff) != approved_diff.diff:
                        approved_diffs.create(parse_dry_run(approved_diff.diff))
                for service in services:
                    for device in service.dry_run.output:
                        device.output = parse_dry_run(device.output)
            if inputs.operation == "rollback":
                self.log.info("Rolling back dry-runs to original values")
                for service in services:
                    dry_run = service.dry_run
                    for device in dry_run.output:
                        device.output = dry_run.unaltered_output[device.device].output

        with ncs.maapi.start_write_trans(
            user="admin", context="system", groups=["system"]
        ) as transaction:
            root = ncs.maagic.get_root(transaction)
            approved_diffs = root.bulk_service_actions.approved_diffs
            services = root.bulk_service_actions.services
            # redeploy-ready logic
            if action_input.redeploy_ready:
                inputs = action_input.redeploy_ready
                _redeploy_ready(inputs, services)

            # wildcard logic
            if action_input.wildcards:
                inputs = action_input.wildcards
                _wildcards(inputs, services, approved_diffs)

            # diff approval logic
            if action_input.diff_approval:
                inputs = action_input.diff_approval
                _diff_approval(inputs, services, approved_diffs)

            transaction.apply()
