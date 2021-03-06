import datetime as dt
import typing as t
import random
import re
import asyncio
from enum import Enum

import discord
import wavelink
from discord.ext import commands

URL_REGEX = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"

OPTIONS = {
    "1️⃣": 0,
    "2⃣": 1,
    "3⃣": 2,
    "4⃣": 3,
    "5⃣": 4,
}

# different errors


class AlreadyConnectedToChannel(commands.CommandError):
    pass


class NoVoiceChannel(commands.CommandError):
    pass


class QueueIsEmpty(commands.CommandError):
    pass


class NoTracksFound(commands.CommandError):
    pass


class PlayerIsAlreadyPaused(commands.CommandError):
    pass


class NoMoreTracks(commands.CommandError):
    pass


class NoPreviousTracks(commands.CommandError):
    pass


class InvalidRepeatMode(commands.CommandError):
    pass


class RepeatMode(Enum):
    NONE = 0
    ONE = 1
    ALL = 2


class Queue:
    def __init__(self):
        self._queue = []
        self.position = 0
        self.repeat_mode = RepeatMode.NONE

    @property
    def is_empty(self):
        return not self._queue

    @property
    def current_track(self):
        if not self._queue:
            raise QueueIsEmpty
        if self.position <= len(self._queue) - 1:
            return self._queue[self.position]

    @property
    def nextInQueue(self):
        if not self._queue:
            raise QueueIsEmpty

        return self._queue[self.position + 1:]

    @property
    def previousInQueue(self):
        if not self._queue:
            raise QueueIsEmpty

        return self._queue[:self.position]

    # @property
    # def lengthh(self):
    #     return len(self._queue)

    def add(self, *args):
        self._queue.extend(args)  # multiple append

    def get_next_track(self):
        if not self._queue:
            raise QueueIsEmpty

        self.position += 1

        if self.position < 0:
            return None
        elif self.position > len(self._queue) - 1:
            if self.repeat_mode == RepeatMode.ALL:
                self.position = 0
            else:
                return None

        return self._queue[self.position]

    def shuffle(self):
        if not self._queue:
            raise QueueIsEmpty

        # shuffle nextInQueue tracks
        nextInQueue = self.nextInQueue
        random.shuffle(nextInQueue)
        self._queue = self._queue[:self.position + 1]
        self._queue.extend(nextInQueue)

    def set_repeat_mode(self, mode):
        if mode == "none":
            self.repeat_mode = RepeatMode.NONE
        elif mode == "1":
            self.repeat_mode = RepeatMode.ONE
        elif mode == "all":
            self.repeat_mode = RepeatMode.ALL

    def empty_queue(self):
        self._queue.clear()
        self.position = 0


class Player(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = Queue()

    async def connect(self, context, channel=None):
        if self.is_connected:
            raise AlreadyConnectedToChannel
        channel = getattr(context.author.voice, "channel", channel)
        if channel is None:
            raise NoVoiceChannel

        await super().connect(channel.id)
        return channel

    async def teardown(self):
        try:
            await self.destroy()
        except KeyError:
            pass

    async def add_tracks(self, context, tracks):
        if not tracks:
            raise NoTracksFound

        if isinstance(tracks, wavelink.TrackPlaylist):
            self.queue.add(*tracks.tracks)
        elif len(tracks) == 1:
            self.queue.add(tracks[0])
            await context.send(f"Added {tracks[0].title} to the Queue.")
        else:
            track = await self.choose_track(context, tracks)
            if track is not None:
                self.queue.add(track)
                await context.send(f"Added {track.title} to the Queue.")

        if not self.is_playing and not self.queue.is_empty:
            await self.start_playback()
    # SEARCH FOR MUSIC

    async def choose_track(self, context, tracks):  # choose from queue
        def _check(reaction, user):
            return (
                reaction.emoji in OPTIONS.keys()
                and user == context.author
                and reaction.message.id == msg.id
            )

        embed = discord.Embed(  # create the 'look' of the queue
            title="Choose a song",
            description=(
                "\n".join(  # length - microseconds
                    f"**{i+1}.** {track.title} ({track.length//60000}:{str(track.length%60).zfill(2)})"
                    for i, track in enumerate(tracks[:5])
                )
            ),
            colour=context.author.colour,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_author(name="Query Results")
        embed.set_footer(
            text=f"Invoked by {context.author.display_name}", icon_url=context.author.avatar_url)

        msg = await context.send(embed=embed)
        for emoji in list(OPTIONS.keys())[:min(len(tracks), len(OPTIONS))]:
            await msg.add_reaction(emoji)

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=60.0, check=_check)
        except asyncio.TimeoutError:
            await msg.delete()
            await context.message.delete()
        else:
            await msg.delete()
            return tracks[OPTIONS[reaction.emoji]]

    async def start_playback(self):
        await self.play(self.queue.current_track)

    async def advance(self):
        try:
            track = self.queue.get_next_track()
            if track is not None:
                await self.play(track)
        except QueueIsEmpty:
            pass

    async def repeat_tracks(self):
        await self.play(self.queue.current_track)


class Music(commands.Cog, wavelink.WavelinkMixin):
    def __init__(self, bot):
        self.bot = bot
        self.wavelink = wavelink.Client(bot=bot)
        self.bot.loop.create_task(self.start_nodes())

    @commands.Cog.listener()
    # when a member joins or leave the channel - voice channel
    async def on_voice_state_update(self, member, before, after):
        # if member (human) left the voice channel
        if not member.bot and after.channel is None:
            # if there aren't members in channel
            if not [m for m in before.channel.members if not m.bot]:
                # disconnect the bot from the channel
                await self.get_player(member.guild).teardown()

    @wavelink.WavelinkMixin.listener()
    async def on_node_ready(self, node):  # what the client connects to
        print(f" Wavelink node '{node.identifier}' ready.")

    @wavelink.WavelinkMixin.listener("on_track_stuck")
    @wavelink.WavelinkMixin.listener("on_track_end")
    @wavelink.WavelinkMixin.listener("on_track_exception")
    async def on_player_stop(self, node, payload):
        if payload.player.queue.repeat_mode == RepeatMode.ONE:
            await payload.player.repeat_tracks()
        else:
            await payload.player.advance()

    async def cogcheck(self, context):
        if isinstance(context.channel, discord.DMChannel):
            await context.send("Music commands are not available in DMs.")
            return False
        return True

    async def start_nodes(self):
        await self.bot.wait_until_ready()

        nodes = {
            "MAIN": {
                "host": "127.0.0.1",
                "port": 2333,
                "rest_uri": "http://127.0.0.1:2333",
                "password": "youshallnotpass",  # for local host - not working if not this
                "identifier": "MAIN",
                "region": "europe",
            }
        }

        for node in nodes.values():
            await self.wavelink.initiate_node(**node)

    def get_player(self, obj):
        if isinstance(obj, commands.Context):
            return self.wavelink.get_player(obj.guild.id, cls=Player, context=obj)
        elif isinstance(obj, discord.Guild):
            return self.wavelink.get_player(obj.id, cls=Player)

    @commands.command(name="connect", aliases=["join"])
    async def connect_command(self, context, *, channel: t.Optional[discord.VoiceChannel]):
        player = self.get_player(context)
        channel = await player.connect(context, channel)
        await context.send(f"Connected to {channel.name}.")

    @connect_command.error
    async def connect_command_error(self, context, exception):
        if isinstance(exception, AlreadyConnectedToChannel):
            await context.send("Already connected to a voice channel")
        elif isinstance(exception, NoVoiceChannel):
            await context.send("No suitable voice channel")

    @commands.command(name="disconnect", aliases=["leave"])
    async def disconnect_command(self, context):
        player = self.get_player(context)
        await player.teardown()
        await context.send("Disconnected.")

    @commands.command(name="play")
    async def play_command(self, context, *, query: t.Optional[str]):
        player = self.get_player(context)

        if not player.is_connected:
            await player.connect(context)

        if query is None:  # resume playback
            if player.queue.is_empty:
                raise QueueIsEmpty

            await player.set_pause(False)  # resume
            await context.send("Playback resumed")
        else:
            query = query.strip("<>")
            if not re.match(URL_REGEX, query):
                query = f"ytsearch:{query}"

            await player.add_tracks(context, await self.wavelink.get_tracks(query))

    @play_command.error
    async def play_command_error(self, context, exception):
        if isinstance(exception, QueueIsEmpty):
            await context.send("No songs to play - queue is empty")
        elif isinstance(exception, NoVoiceChannel):
            await context.send("No suitable voice channel")

    @commands.command(name="pause")
    async def pause_command(self, context):
        player = self.get_player(context)

        if player.is_paused:
            raise PlayerIsAlreadyPaused

        await player.set_pause(True)
        await context.send("Playback paused.")

    @pause_command.error
    async def pause_command_error(self, context, exception):
        if isinstance(exception, PlayerIsAlreadyPaused):
            await context.send("Already paused.")

    @commands.command(name="stop")
    async def stop_command(self, context):
        player = self.get_player(context)
        player.queue.empty_queue()
        await player.stop()
        await context.send("Playback stopped.")

    @commands.command(name="next", aliases=["skip"])
    async def next_command(self, context):
        player = self.get_player(context)

        if not player.queue.nextInQueue:
            raise NoMoreTracks

        await player.stop()
        await context.send("Playing next track on queue.")

    @next_command.error
    async def next_command_error(self, context, exception):
        if isinstance(exception, QueueIsEmpty):
            await context.send("A skip could not be executed as the queue is currently empty.")
        elif isinstance(exception, NoMoreTracks):
            await context.send("No more tracks in the queue.")

    @commands.command(name="previous")
    async def previous_command(self, context):
        player = self.get_player(context)

        if not player.queue.previousInQueue:
            raise NoPreviousTracks

        player.queue.position -= 2
        await player.stop()
        await context.send("Playing previous track on queue.")

    @previous_command.error
    async def previous_command_error(self, context, exception):
        if isinstance(exception, QueueIsEmpty):
            await context.send("A skip could not be executed as the queue is currently empty.")
        elif isinstance(exception, NoPreviousTracks):
            await context.send("No previous tracks in the queue.")

    @commands.command(name="shuffle")
    async def shuffle_command(self, context):
        player = self.get_player(context)
        player.queue.shuffle()
        await context.send("Queue shuffled.")

    @shuffle_command.error
    async def shuffle_command_error(self, context, exception):
        if isinstance(exception, QueueIsEmpty):
            await context.send("The queue could not be shuffled as it is currently empty.")

    @commands.command(name="repeat")
    async def repeat_command(self, context, mode: str):
        if mode not in ("none", "1", "all"):
            raise InvalidRepeatMode

        player = self.get_player(context)
        player.queue.set_repeat_mode(mode)
        await context.send(f"The repeat mode has been set to {mode}")

    @commands.command(name="queue")
    async def queue_command(self, context, show: t.Optional[int] = 10):
        player = self.get_player(context)

        if player.queue.is_empty:
            raise QueueIsEmpty

        embed = discord.Embed(
            title="Your queue",
            description=f"Showing up to next {show} tracks",
            colour=context.author.colour,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_author(name="Query Results")
        embed.set_footer(
            text=f"Requested by {context.author.display_name}",
            icon_url=context.author.avatar_url
        )
        embed.add_field(
            name="Currently playing",
            value=getattr(player.queue.current_track, "title", ""),
            inline=False
        )
        nextInQueue = player.queue.nextInQueue
        if nextInQueue:
            embed.add_field(
                name="Next up",
                value="\n"
                .join(track.title for track in nextInQueue[:show]),
                inline=False
            )

        msg = await context.send(embed=embed)

    @queue_command.error
    async def queue_command_error(self, context, exception):
        if isinstance(exception, QueueIsEmpty):
            await context.send("The queue is currently empty.")


def setup(bot):
    bot.add_cog(Music(bot))
