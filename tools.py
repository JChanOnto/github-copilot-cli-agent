"""
tools.py — Custom tools for the GitHub Copilot SDK coding agent.

Each tool is registered with the agent session and available for the model
to invoke during iterations.

Available tools
---------------
analyze_image
    Analyze an image file (JPEG, PNG, GIF, WebP, BMP, …) using vision AI.
    The agent passes an image path and a specific question; the tool spins
    up a short-lived Copilot session with the image attached and returns
    a text answer.
"""

import asyncio
import base64
import mimetypes
from pathlib import Path


def build_custom_tools(github_token: str, model: str) -> list:
    """Build and return the list of custom tools to register with each session.

    Tools are created fresh each call so closures over github_token/model
    are always current.
    """
    # Deferred imports — SDK may not be installed until setup.py runs
    from copilot import CopilotClient, SubprocessConfig, define_tool  # noqa: F401
    from copilot.session import PermissionHandler
    from copilot.generated.session_events import (
        AssistantMessageData,
        SessionIdleData,
    )
    from pydantic import BaseModel, Field

    class AnalyzeImageParams(BaseModel):
        image_path: str = Field(
            description=(
                "Path to the image file to analyze.  "
                "Can be absolute or relative to the working directory."
            )
        )
        question: str = Field(
            description="Specific question to answer about the image contents."
        )

    @define_tool(
        description=(
            "Analyze an image file using vision AI and answer a specific question "
            "about it.  Supports JPEG, PNG, GIF, WebP, BMP and other common "
            "image formats.  Returns a detailed text answer."
        )
    )
    async def analyze_image(params: AnalyzeImageParams) -> str:
        path = Path(params.image_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return f"Error: image file not found: {params.image_path}"

        try:
            image_bytes = path.read_bytes()
            image_data = base64.b64encode(image_bytes).decode("utf-8")
        except OSError as exc:
            return f"Error reading image: {exc}"

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        try:
            async with CopilotClient(
                SubprocessConfig(github_token=github_token)
            ) as vision_client:
                async with await vision_client.create_session(
                    on_permission_request=PermissionHandler.approve_all,
                    model=model,
                ) as vision_session:
                    done_evt = asyncio.Event()
                    result_parts: list[str] = []

                    def on_vision_event(event):
                        match event.data:
                            case AssistantMessageData() as data:
                                result_parts.append(data.content)
                            case SessionIdleData():
                                done_evt.set()

                    vision_session.on(on_vision_event)
                    await vision_session.send(
                        params.question,
                        attachments=[{
                            "type": "blob",
                            "data": image_data,
                            "mimeType": mime_type,
                        }],
                    )
                    try:
                        await asyncio.wait_for(done_evt.wait(), timeout=120)
                    except asyncio.TimeoutError:
                        return "Vision analysis timed out after 120 s."

                    return result_parts[0] if result_parts else "(no analysis returned)"
        except asyncio.TimeoutError:
            return "Vision analysis timed out."
        except (OSError, ValueError) as exc:
            return f"Error during vision analysis: {exc}"
        except asyncio.CancelledError:
            raise

    return [analyze_image]
