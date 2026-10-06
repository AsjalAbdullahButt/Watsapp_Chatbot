"""Chat with the agent in your terminal, no WhatsApp needed.

    python -m scripts.chat                 # as sample customer Ali (linked number)
    python -m scripts.chat --phone 923009999999   # as an unknown number

Needs GROQ_API_KEY in .env. Type 'exit' to quit, 'tools' to toggle the tool trace.
"""

import argparse
import asyncio
import logging

from app.agent.agent import Agent, ConversationMemory
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.data.source import JsonDataSource
from app.llm.groq_provider import GroqProvider
from app.tools.catalog import build_registry


async def main(phone: str) -> None:
    settings = get_settings()
    configure_logging("WARNING")
    logging.getLogger("tools").setLevel("WARNING")
    source = JsonDataSource(settings.data_file)
    llm = GroqProvider(settings.groq_api_key, settings.groq_model, settings.llm_timeout_seconds, settings.llm_max_retries)
    agent = Agent(llm, build_registry(source), source, ConversationMemory(settings.history_messages), settings.max_tool_steps)
    show_tools = True
    customer = source.find_customer_by_phone(phone)
    print(f"Chatting as {phone} ({customer.name if customer else 'not a known customer'}). Model: {settings.groq_model}")
    try:
        while True:
            text = await asyncio.to_thread(input, "\nYou: ")
            if text.strip().lower() in {"exit", "quit"}:
                break
            if text.strip().lower() == "tools":
                show_tools = not show_tools
                print(f"[tool trace {'on' if show_tools else 'off'}]")
                continue
            if not text.strip():
                continue
            reply = await agent.reply(phone, text)
            if show_tools:
                for t in reply.tools:
                    print(f"  [tool] {t.tool}({t.arguments}) -> {t.status}")
            print(f"Bot: {reply.text}")
    finally:
        await llm.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", default="923001234567")
    asyncio.run(main(parser.parse_args().phone))
