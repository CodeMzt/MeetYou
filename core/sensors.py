from prompt_toolkit import Application
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings

from core.context import sensory_queue
from core.context import shutdown_event


output_field = TextArea(text="", read_only=True, scrollbar=True)
input_field = TextArea(height=5, prompt="User: ", multiline=False)

def system_output(text: str):
    output_field.text += text + "\n"
    output_field.buffer.cursor_position = len(output_field.text)
    try:
        app.invalidate()
    except Exception:
        pass

container = HSplit([
    output_field, 
    Window(height=1, char='='), # 用等号作为中间的分隔线
    input_field
])

layout = Layout(container, focused_element=input_field)

kb = KeyBindings()

@kb.add('c-c')
def handle_exit(event):
    event.app.exit()

@kb.add('enter')
def handle_enter(event):
    user_text = input_field.text
    if user_text.strip():
        if user_text == "exit":
            event.app.exit()
            return
        output_field.text += f"You: {user_text}\n"
        output_field.buffer.cursor_position = len(output_field.text)
        sensory_queue.put_nowait({
            "source": "user",
            "content": user_text
        })
    input_field.text = ""

app = Application(
    layout=layout,      
    key_bindings=kb,    
    full_screen=True,    # 全屏模式
    mouse_support=True,   
)

async def listener():
    try:
        await app.run_async()
    except Exception as e:
        raise e
    finally:
        output_field.text += "\nMozart: 哎，回见！\n"
        output_field.buffer.cursor_position = len(output_field.text)
        shutdown_event.set()

