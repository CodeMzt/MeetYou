"""
CLI 输出适配器。
"""

from core.io_protocol import EventType, StreamEventType


class CLIOutputAdapter:
    """
    只负责把统一输出事件渲染到 CLI 界面。
    """

    def __init__(self, app, output_field, input_field):
        self._app = app
        self._output_field = output_field
        self._input_field = input_field

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
            if stream_event == StreamEventType.CHUNK.value:
                self._append(str(event.content).replace("\r", ""))
                return
            self._append(f"Mozart: {event.content}\n")
