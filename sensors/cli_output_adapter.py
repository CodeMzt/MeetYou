"""
CLI 输出适配器。
"""

from core.io_protocol import EventType, StreamEventType


class CLIOutputAdapter:
    """
    负责把统一输出事件渲染到 CLI 界面。
    """

    def __init__(self, app, output_field, input_field):
        self._app = app
        self._output_field = output_field
        self._input_field = input_field
        self._answer_streaming = False
        self._answer_prefix_pending = False

    def _append(self, text: str):
        self._output_field.text += text
        self._output_field.buffer.cursor_position = len(self._output_field.text)
        try:
            self._app.invalidate()
        except Exception:
            pass

    async def send(self, event):
        stream_event = event.metadata.get("stream_event", "")

        if event.type == EventType.CONFIRM_REQUEST.value:
            prompt = str(event.content)
            self._input_field.text = ""
            self._append(f"\n{'=' * 50}\n{prompt}\n{'=' * 50}\n")
            return

        if event.type == EventType.HUMAN_INPUT_REQUEST.value:
            prompt = str(getattr(event, "question", "") or event.content)
            options = [str(item).strip() for item in getattr(event, "options", []) if str(item).strip()]
            option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
            block = f"\n{'=' * 50}\n{prompt}"
            if option_lines:
                block += f"\n{option_lines}"
            block += f"\n{'=' * 50}\n"
            self._input_field.text = ""
            self._append(block)
            return

        if event.type == EventType.ERROR.value:
            self._append(f"\n[系统错误] {event.content}\n")
            return

        if event.type == EventType.STATUS.value:
            if stream_event == StreamEventType.START.value:
                self._append("Mozart: ")
                return
            if stream_event == StreamEventType.END.value:
                self._append("\n")
                return
            if event.content:
                self._append(f"[系统] {event.content}\n")
            return

        if event.type == EventType.MESSAGE.value:
            if stream_event == StreamEventType.START.value:
                self._answer_streaming = True
                self._answer_prefix_pending = True
                return
            if stream_event == StreamEventType.CHUNK.value:
                content = str(event.content).replace("\r", "")
                if content:
                    if self._answer_prefix_pending:
                        self._append("Mozart: ")
                        self._answer_prefix_pending = False
                    self._append(content)
                self._answer_streaming = True
                return
            if stream_event == StreamEventType.END.value:
                if self._answer_streaming and not self._answer_prefix_pending:
                    self._append("\n")
                self._answer_streaming = False
                self._answer_prefix_pending = False
                return
            if self._answer_streaming and not self._answer_prefix_pending:
                self._append("\n")
            self._answer_streaming = False
            self._answer_prefix_pending = False
            self._append(f"Mozart: {event.content}\n")
