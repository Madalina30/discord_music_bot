from pathlib import Path

import discord
from discord.ext import commands

class MusicBot(commands.Bot):
    def __init__(self):
        self._cogs = [p.stem for p in Path(".").glob("./bot/cogs/*.py")] 
        super().__init__(command_prefix=self.prefix, case_insensitive=True, intents=discord.Intents.all())

    def setup(self):  # set up bot
        print("Running setup...")

        for cog in self._cogs:
            self.load_extension(f"bot.cogs.{cog}")
            print(f" Loaded `{cog}` cog.")

        print("Setup complete.")

    def run(self):
        self.setup()

        with open("data/token.0", "r", encoding="utf-8") as f:
            TOKEN = f.read()
        
        print("Bot running...")
        super().run(TOKEN, reconnect=True)  # reconnect discord if fails

    async def shutdown(self):
        print(" Closing connection to Discord... ")
        await super().close()

    async def close(self):  # when pressed ctrl+c
        print("Closing on keyboard interrupt...")
        await self.shutdown()

    async def on_connect(self):
        print(f"Connected to Discord (latency: {self.latency*1000} ms).")
    
    async def on_resumed(self):
        print("Bot resumed")

    async def on_disconnect(self):
        print("Bot disconnected.")

    async def on_ready(self):
        self.client_id = (await self.application_info()).id
        print("Bot ready.")

    async def prefix(self, bot, msg):
        return commands.when_mentioned_or("~")(bot, msg)
    
    async def process_commands(self, msg):
        context = await self.get_context(msg, cls=commands.Context)

        if context.command is not None:
            await self.invoke(context)

    async def on_message(self, msg):
        if not msg.author.bot:
            await self.process_commands(msg)
