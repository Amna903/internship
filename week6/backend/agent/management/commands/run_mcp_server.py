"""Run the MCP server over stdio (Week 5 Step 9). Started by a local MCP client, which passes the token in
HEALTHPROFILE_MCP_TOKEN. Nothing but MCP messages may go to stdout, so this command prints nothing."""

import anyio
from django.core.management.base import BaseCommand
from mcp.server.stdio import stdio_server

from agent.mcp_server import build_server, token_from_env


class Command(BaseCommand):
    help = "Run the MCP server over stdio (the token comes from HEALTHPROFILE_MCP_TOKEN)."

    def handle(self, *args, **options):
        server = build_server(token_from_env())

        async def main():
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())

        anyio.run(main)
