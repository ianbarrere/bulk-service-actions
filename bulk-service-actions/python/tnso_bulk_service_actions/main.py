# -*- mode: python; python-indent: 4 -*-
""" Main function to register Services and Actions """
import ncs

from .bulk_service_actions import (
    ServiceList,
    RedeployTopLevel,
    ReconcileSublayers,
    ServiceListTools,
    BulkServiceActionScheduler,
    BulkServiceActionServiceListService,
)


class Main(ncs.application.Application):
    """Register all Services and Actions for this module"""

    def setup(self) -> None:
        self.log.info("Main RUNNING")
        ServiceList.attach_to(self, "service-list")
        RedeployTopLevel.attach_to(self, "redeploy-top-level")
        ReconcileSublayers.attach_to(self, "reconcile-sublayers")
        ServiceListTools.attach_to(self, "service-list-tools")
        self.register_service(
            "bulk-service-actions-scheduler", BulkServiceActionScheduler
        )
        self.register_service(
            "bulk-service-actions-service-list-service",
            BulkServiceActionServiceListService,
        )

    def teardown(self) -> None:
        self.log.info("Main FINISHED")
