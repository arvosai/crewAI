from __future__ import annotations

import asyncio
import json
import os
import platform
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional


@contextmanager
def suppress_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        yield


with suppress_warnings():
    import pkg_resources


from opentelemetry import trace  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,  # noqa: E402
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: E402
from opentelemetry.trace import Span, Status, StatusCode  # noqa: E402

from crewai.utilities.event_emitter import CrewEvents, crew_events

if TYPE_CHECKING:
    from crewai.crew import Crew
    from crewai.task import Task


class Telemetry:
    """A class to handle anonymous telemetry for the crewai package.

    The data being collected is for development purpose, all data is anonymous.

    There is NO data being collected on the prompts, tasks descriptions
    agents backstories or goals nor responses or any data that is being
    processed by the agents, nor any secrets and env vars.

    Users can opt-in to sharing more complete data using the `share_crew`
    attribute in the Crew class.
    """

    def __init__(self):
        self.ready = False
        self.trace_set = False
        try:
            telemetry_endpoint = "https://telemetry.crewai.com:4319"
            self.resource = Resource(
                attributes={SERVICE_NAME: "crewAI-telemetry"},
            )
            with suppress_warnings():
                self.provider = TracerProvider(resource=self.resource)

            processor = BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=f"{telemetry_endpoint}/v1/traces",
                    timeout=30,
                )
            )

            self.provider.add_span_processor(processor)
            self.ready = True
        except BaseException as e:
            if isinstance(
                e,
                (SystemExit, KeyboardInterrupt, GeneratorExit, asyncio.CancelledError),
            ):
                raise  # Re-raise the exception to not interfere with system signals
            self.ready = False

    def set_tracer(self):
        if self.ready and not self.trace_set:
            try:
                with suppress_warnings():
                    trace.set_tracer_provider(self.provider)
                    self.trace_set = True
            except Exception:
                self.ready = False
                self.trace_set = False

    def crew_creation(
        self, crew_data: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None
    ):
        """Records the creation of a crew."""
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Crew Created")

                # Accessing data from the serialized crew dictionary
                self._add_attribute(
                    span, "crewai_version", crew_data.get("crewai_version")
                )
                self._add_attribute(span, "python_version", platform.python_version())
                self._add_attribute(span, "crew_key", crew_data.get("key"))
                self._add_attribute(span, "crew_id", crew_data.get("id"))
                self._add_attribute(span, "crew_process", crew_data.get("process"))
                self._add_attribute(span, "crew_memory", crew_data.get("memory"))
                self._add_attribute(
                    span, "crew_number_of_tasks", len(crew_data.get("tasks", []))
                )
                self._add_attribute(
                    span, "crew_number_of_agents", len(crew_data.get("agents", []))
                )

                if crew_data.get("share_crew"):
                    self._add_attribute(
                        span, "crew_agents", json.dumps(crew_data.get("agents", []))
                    )
                    self._add_attribute(
                        span, "crew_tasks", json.dumps(crew_data.get("tasks", []))
                    )
                    self._add_attribute(span, "platform", platform.platform())
                    self._add_attribute(span, "platform_release", platform.release())
                    self._add_attribute(span, "platform_system", platform.system())
                    self._add_attribute(span, "platform_version", platform.version())
                    self._add_attribute(span, "cpus", os.cpu_count())
                    self._add_attribute(
                        span, "crew_inputs", json.dumps(inputs) if inputs else None
                    )
                else:
                    # Handle the case where share_crew is False
                    # You might want to add limited data here
                    pass

                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def task_started(self, crew: Crew, task: Task) -> Span | None:
        """Records task started in a crew."""
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")

                created_span = tracer.start_span("Task Created")

                self._add_attribute(created_span, "crew_key", crew.key)
                self._add_attribute(created_span, "crew_id", str(crew.id))
                self._add_attribute(created_span, "task_key", task.key)
                self._add_attribute(created_span, "task_id", str(task.id))

                if crew.share_crew:
                    self._add_attribute(
                        created_span, "formatted_description", task.description
                    )
                    self._add_attribute(
                        created_span, "formatted_expected_output", task.expected_output
                    )

                created_span.set_status(Status(StatusCode.OK))
                created_span.end()

                span = tracer.start_span("Task Execution")

                self._add_attribute(span, "crew_key", crew.key)
                self._add_attribute(span, "crew_id", str(crew.id))
                self._add_attribute(span, "task_key", task.key)
                self._add_attribute(span, "task_id", str(task.id))

                if crew.share_crew:
                    self._add_attribute(span, "formatted_description", task.description)
                    self._add_attribute(
                        span, "formatted_expected_output", task.expected_output
                    )

                return span
            except Exception:
                pass

        return None

    def task_ended(self, span: Span, task: Task, crew: Crew):
        """Records task execution in a crew."""
        if self.ready:
            try:
                if crew.share_crew:
                    self._add_attribute(
                        span,
                        "task_output",
                        task.output.raw if task.output else "",
                    )

                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def tool_repeated_usage(self, llm: Any, tool_name: str, attempts: int):
        """Records the repeated usage 'error' of a tool by an agent."""
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Tool Repeated Usage")
                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(span, "tool_name", tool_name)
                self._add_attribute(span, "attempts", attempts)
                if llm:
                    self._add_attribute(span, "llm", llm.model)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def tool_usage(self, llm: Any, tool_name: str, attempts: int):
        """Records the usage of a tool by an agent."""
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Tool Usage")
                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(span, "tool_name", tool_name)
                self._add_attribute(span, "attempts", attempts)
                if llm:
                    self._add_attribute(span, "llm", llm.model)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def tool_usage_error(self, llm: Any):
        """Records the usage of a tool by an agent."""
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Tool Usage Error")
                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                if llm:
                    self._add_attribute(span, "llm", llm.model)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def individual_test_result_span(
        self, crew: Crew, quality: float, exec_time: int, model_name: str
    ):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Crew Individual Test Result")

                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(span, "crew_key", crew.key)
                self._add_attribute(span, "crew_id", str(crew.id))
                self._add_attribute(span, "quality", str(quality))
                self._add_attribute(span, "exec_time", str(exec_time))
                self._add_attribute(span, "model_name", model_name)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def test_execution_span(
        self,
        crew: Crew,
        iterations: int,
        inputs: dict[str, Any] | None,
        model_name: str,
    ):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Crew Test Execution")

                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(span, "crew_key", crew.key)
                self._add_attribute(span, "crew_id", str(crew.id))
                self._add_attribute(span, "iterations", str(iterations))
                self._add_attribute(span, "model_name", model_name)

                if crew.share_crew:
                    self._add_attribute(
                        span, "inputs", json.dumps(inputs) if inputs else None
                    )

                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def deploy_signup_error_span(self):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Deploy Signup Error")
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def start_deployment_span(self, uuid: Optional[str] = None):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Start Deployment")
                if uuid:
                    self._add_attribute(span, "uuid", uuid)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def create_crew_deployment_span(self):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Create Crew Deployment")
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def get_crew_logs_span(self, uuid: Optional[str], log_type: str = "deployment"):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Get Crew Logs")
                self._add_attribute(span, "log_type", log_type)
                if uuid:
                    self._add_attribute(span, "uuid", uuid)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def remove_crew_span(self, uuid: Optional[str] = None):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Remove Crew")
                if uuid:
                    self._add_attribute(span, "uuid", uuid)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def crew_execution_span(
        self, crew_data: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None
    ):
        """Records the complete execution of a crew.
        This is only collected if the user has opted-in to share the crew.
        """
        if self.ready and crew_data.get("share_crew"):
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Crew Execution")

                self._add_attribute(
                    span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(span, "crew_key", crew_data.get("key"))
                self._add_attribute(span, "crew_id", crew_data.get("id"))
                self._add_attribute(
                    span, "crew_inputs", json.dumps(inputs) if inputs else None
                )
                self._add_attribute(
                    span,
                    "crew_agents",
                    json.dumps(crew_data.get("agents", [])),
                )
                self._add_attribute(
                    span,
                    "crew_tasks",
                    json.dumps(crew_data.get("tasks", [])),
                )
                span.set_status(Status(StatusCode.OK))
                span.end()
                return span
            except Exception:
                pass

    def end_crew(self, crew, final_string_output):
        if (self.ready) and (crew.share_crew):
            try:
                self._add_attribute(
                    crew._execution_span,
                    "crewai_version",
                    pkg_resources.get_distribution("crewai").version,
                )
                self._add_attribute(
                    crew._execution_span, "crew_output", final_string_output
                )
                self._add_attribute(
                    crew._execution_span,
                    "crew_tasks_output",
                    json.dumps(
                        [
                            {
                                "id": str(task.id),
                                "description": task.description,
                                "output": task.output.raw_output,
                            }
                            for task in crew.tasks
                        ]
                    ),
                )
                crew._execution_span.set_status(Status(StatusCode.OK))
                crew._execution_span.end()
            except Exception:
                pass

    def _add_attribute(self, span, key, value):
        """Add an attribute to a span."""
        try:
            return span.set_attribute(key, value)
        except Exception:
            pass

    def flow_creation_span(self, flow_name: str):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Flow Creation")
                self._add_attribute(span, "flow_name", flow_name)
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def flow_plotting_span(self, flow_name: str, node_names: list[str]):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Flow Plotting")
                self._add_attribute(span, "flow_name", flow_name)
                self._add_attribute(span, "node_names", json.dumps(node_names))
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass

    def flow_execution_span(self, flow_name: str, node_names: list[str]):
        if self.ready:
            try:
                tracer = trace.get_tracer("crewai.telemetry")
                span = tracer.start_span("Flow Execution")
                self._add_attribute(span, "flow_name", flow_name)
                self._add_attribute(span, "node_names", json.dumps(node_names))
                span.set_status(Status(StatusCode.OK))
                span.end()
            except Exception:
                pass


telemetry = Telemetry()


crew_events.on(CrewEvents.CREW_START, telemetry.crew_execution_span)
