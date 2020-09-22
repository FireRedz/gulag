# -*- coding: utf-8 -*-

from typing import Tuple, Final, Callable
import time
import bcrypt

from cmyui import rstring

import packets
from packets import Packet, PacketReader # convenience

from console import *
from constants.types import osuTypes
from constants.mods import Mods
from constants import commands
from constants import regexes
from objects import glob
from objects.score import Rank
from objects.match import SlotStatus, Teams
from objects.player import Player, PresenceFilter, Action
from objects.beatmap import Beatmap
from constants.privileges import Privileges

glob.bancho_map = {}

def bancho_packet(ID: int) -> Callable:
    def register_callback(callback: Callable) -> Callable:
        glob.bancho_map.update({ID: callback})
        return callback
    return register_callback

# PacketID: 0
@bancho_packet(Packet.c_changeAction)
async def readStatus(p: Player, pr: PacketReader) -> None:
    data = await pr.read(
        osuTypes.u8, # actionType
        osuTypes.string, # infotext
        osuTypes.string, # beatmap md5
        osuTypes.u32, # mods
        osuTypes.u8, # gamemode
        osuTypes.i32 # beatmapid
    )

    p.status.update(*data)
    p.rx = p.status.mods & Mods.RELAX > 0
    glob.players.enqueue(await packets.userStats(p))

# PacketID: 1
@bancho_packet(Packet.c_sendPublicMessage)
async def sendMessage(p: Player, pr: PacketReader) -> None:
    if p.silenced:
        await plog(f'{p} tried to send a message while silenced.', Ansi.YELLOW)
        return

    # client_id only proto >= 14
    client, msg, target, client_id = await pr.read(osuTypes.message)

    # no nice wrapper to do it in reverse :P
    if target == '#spectator':
        target = f'#spec_{p.spectating.id if p.spectating else p.id}'
    elif target == '#multiplayer':
        target = f'#multi_{p.match.id if p.match is not None else 0}'

    if not (t := glob.channels.get(target)):
        await plog(f'{p} tried to write to non-existant {target}.', Ansi.YELLOW)
        return

    if not p.priv & t.write:
        await plog(f'{p} tried to write to {target} without privileges.')
        return

    # Limit message length to 2048 characters
    msg = f'{msg[:2045]}...' if msg[2048:] else msg
    client, client_id = p.name, p.id

    cmd = msg.startswith(glob.config.command_prefix) \
      and await commands.process_commands(p, t, msg)

    if cmd: # A command was triggered.
        if cmd['public']:
            await t.send(p, msg)
            if 'resp' in cmd:
                await t.send(glob.bot, cmd['resp'])
        else:
            staff = glob.players.staff
            await t.send_selective(p, msg, staff - {p})
            if 'resp' in cmd:
                await t.send_selective(glob.bot, cmd['resp'], {p} | staff)

    else: # No command was triggered.
        if _match := regexes.now_playing.match(msg):
            # User is /np'ing a map.
            # Save it to their player instance
            # so we can use this elsewhere owo..
            p.last_np = await Beatmap.from_bid(int(_match['bid']))

        await t.send(p, msg)

    await plog(f'{p} @ {t}: {msg}', Ansi.CYAN, fd = 'logs/chat.log')

# PacketID: 2
@bancho_packet(Packet.c_logout)
async def logout(p: Player, pr: PacketReader) -> None:
    pr.ignore(4) # osu client sends \x00\x00\x00\x00 every time lol

    if (time.time() - p.login_time) < 2:
        # osu! has a weird tendency to log out immediately when
        # it logs in, then reconnects? not sure why..?
        return

    await p.logout()
    await plog(f'{p} logged out.', Ansi.LIGHT_YELLOW)

# PacketID: 3
@bancho_packet(Packet.c_requestStatusUpdate)
async def statsUpdateRequest(p: Player, pr: PacketReader) -> None:
    p.enqueue(await packets.userStats(p))

# PacketID: 4
@bancho_packet(Packet.c_ping)
async def ping(p: Player, pr: PacketReader) -> None:
    # TODO: this should be last packet time, not just
    # ping.. this handler shouldn't even exist lol
    p.ping_time = int(time.time())

registration_msg: Final[str] = '\n'.join((
    "Hey! Welcome to the gulag.",
    "",
    "Since it's your first time here, I thought i'd show you around a bit.",
    "Command help: !help",
    "",
    "If you have any questions or find any strange behaviour,",
    "please feel feel free to contact cmyui(#0425) directly!",
    "",
    "Staff online: {}.",
    "Source code: https://github.com/cmyui/gulag/"
))
# No specific packetID, triggered when the
# client sends a request without an osu-token.
async def login(origin: bytes, ip: str) -> Tuple[bytes, str]:
    # Login is a bit special, we return the response bytes
    # and token in a tuple - we need both for our response.

    s = origin.decode().split('\n')

    if p := await glob.players.get_by_name(username := s[0]):
        if (time.time() - p.ping_time) > 10:
            # If the current player obj online hasn't
            # pinged the server in > 10 seconds, log
            # them out and login the new user.
            await p.logout()
        else: # User is currently online, send back failure.
            return (await packets.notification('User already logged in.') +
                    await packets.userID(-1), 'no')

    del p

    pw_hash = s[1].encode()

    s = s[2].split('|')
    build_name = s[0]

    if not s[1].replace('-', '', 1).isdecimal():
        return await packets.userID(-1), 'no'

    utc_offset = int(s[1])
    display_city = s[2] == '1'

    # Client hashes contain a few values useful to us.
    # [0]: md5(osu path)
    # [1]: adapters (network physical addresses delimited by '.')
    # [2]: md5(adapters)
    # [3]: md5(uniqueid) (osu! uninstall id)
    # [4]: md5(uniqueid2) (disk signature/serial num)
    client_hashes = s[3].split(':')[:-1]

    pm_private = s[4] == '1'

    res = await glob.db.fetch(
        'SELECT id, name, priv, pw_hash, silence_end '
        'FROM users WHERE name_safe = %s',
        [Player.ensure_safe(username)])

    # Get our bcrypt cache.
    bcrypt_cache = glob.cache['bcrypt']

    if res:
        # Account exists.
        # Check their account status & credentials against db.
        if not res['priv'] & Privileges.Normal:
            return await packets.userID(-3), 'no'

        # Password is incorrect.
        if pw_hash in bcrypt_cache: # ~0.01 ms
            # Cache hit - this saves ~200ms on subsequent logins.
            if bcrypt_cache[pw_hash] != res['pw_hash']:
                return await packets.userID(-1), 'no'
        else: # Cache miss, must be first login.
            if not bcrypt.checkpw(pw_hash, res['pw_hash'].encode()):
                return await packets.userID(-1), 'no'

            bcrypt_cache[pw_hash] = res['pw_hash']

        p = Player(utc_offset = utc_offset,
                   pm_private = pm_private,
                   **res)
    else:
        # Account does not exist, register using credentials passed.
        pw_bcrypt = bcrypt.hashpw(pw_hash, bcrypt.gensalt()).decode()
        bcrypt_cache[pw_hash] = pw_bcrypt

        # Add to `users` table.
        user_id = await glob.db.execute(
            'INSERT INTO users (name, name_safe, pw_hash, email) '
            'VALUES (%s, %s, %s, %s)', [
                username, Player.ensure_safe(username),
                pw_bcrypt, f'{rstring(6)}@gmail.com'
            ]
        )

        # Add to `stats` table.
        await glob.db.execute('INSERT INTO stats (id) VALUES (%s)', [user_id])

        p = Player(id = user_id, name = username,
                   priv = Privileges.Normal,
                   silence_end = 0)

        await plog(f'{p} has registered!', Ansi.LIGHT_GREEN)

        # Enqueue registration message to the user.
        _msg = registration_msg.format(glob.players.staff)
        p.enqueue(await packets.sendMessage(
            glob.bot.name, _msg, p.name, p.id
        ))

    data = bytearray(
        await packets.userID(p.id) +
        await packets.protocolVersion(19) +
        await packets.banchoPrivileges(p.bancho_priv) +
        await packets.notification(f'Welcome back to the gulag!\nCurrent build: {glob.version}') +

        # Tells osu! to load channels from config, I believe?
        await packets.channelInfoEnd()
    )

    # Channels
    for c in glob.channels:
        if not p.priv & c.read:
            continue # no priv to read

        # Autojoinable channels
        if c.auto_join and await p.join_channel(c):
            # NOTE: p.join_channel enqueues channelJoin, but
            # if we don't send this back in this specific request,
            # the client will attempt to join the channel again.
            data.extend(await packets.channelJoin(c.name))

        data.extend(await packets.channelInfo(*c.basic_info))

    # Fetch some of the player's
    # information from sql to be cached.
    await p.stats_from_sql_full()
    await p.friends_from_sql()

    if glob.config.server_build:
        # Update their country data with
        # the IP from the login request.
        await p.fetch_geoloc(ip)

    # Update our new player's stats, and broadcast them.
    user_data = (await packets.userPresence(p) +
                 await packets.userStats(p))

    data.extend(user_data)

    # o for online, or other
    for o in glob.players:
        # Enqueue us to them
        o.enqueue(user_data)

        # Enqueue them to us.
        data.extend(await packets.userPresence(o) +
                    await packets.userStats(o))

    data.extend(await packets.mainMenuIcon() +
                await packets.friendsList(*p.friends) +
                await packets.silenceEnd(max(p.silence_end - time.time(), 0)))

    await glob.players.add(p)
    await plog(f'{p} logged in.', Ansi.LIGHT_YELLOW)
    return bytes(data), p.token

# PacketID: 16
@bancho_packet(Packet.c_startSpectating)
async def startSpectating(p: Player, pr: PacketReader) -> None:
    target_id, = await pr.read(osuTypes.i32)

    if not (host := await glob.players.get_by_id(target_id)):
        await plog(f'{p} tried to spectate nonexistant id {target_id}.', Ansi.YELLOW)
        return

    if (c_host := p.spectating):
        await c_host.remove_spectator(p)

    await host.add_spectator(p)

# PacketID: 17
@bancho_packet(Packet.c_stopSpectating)
async def stopSpectating(p: Player, pr: PacketReader) -> None:
    host: Player = p.spectating

    if not host:
        await plog(f"{p} tried to stop spectating when they're not..?", Ansi.LIGHT_RED)
        return

    await host.remove_spectator(p)

# PacketID: 18
@bancho_packet(Packet.c_spectateFrames)
async def spectateFrames(p: Player, pr: PacketReader) -> None:
    data = await packets.spectateFrames(pr.data[:pr.length])
    pr.ignore_packet()
    for t in p.spectators:
        t.enqueue(data)

# PacketID: 21
@bancho_packet(Packet.c_cantSpectate)
async def cantSpectate(p: Player, pr: PacketReader) -> None:
    if not p.spectating:
        await plog(f"{p} sent can't spectate while not spectating?", Ansi.LIGHT_RED)
        return

    data = await packets.spectatorCantSpectate(p.id)

    host: Player = p.spectating
    host.enqueue(data)

    for t in host.spectators:
        t.enqueue(data)

# PacketID: 25
@bancho_packet(Packet.c_sendPrivateMessage)
async def sendPrivateMessage(p: Player, pr: PacketReader) -> None:
    if p.silenced:
        await plog(f'{p} tried to send a dm while silenced.', Ansi.YELLOW)
        return

    client, msg, target, client_id = await pr.read(osuTypes.message)

    if not (t := await glob.players.get_by_name(target)):
        await plog(f'{p} tried to write to non-existant user {target}.', Ansi.YELLOW)
        return

    if t.pm_private and p.id not in t.friends:
        p.enqueue(await packets.userPMBlocked(target))
        await plog(f'{p} tried to message {t}, but they are blocking dms.')
        return

    if t.silenced:
        p.enqueue(await packets.targetSilenced(target))
        await plog(f'{p} tried to message {t}, but they are silenced.')
        return

    msg = f'{msg[:2045]}...' if msg[2048:] else msg
    client, client_id = p.name, p.id

    if t.status.action == Action.Afk and t.away_msg:
        # Send away message if target is afk and has one set.
        p.enqueue(await packets.sendMessage(client, t.away_msg, target, client_id))

    if t.id == 1:
        # Target is Aika, check if message is a command.
        cmd = msg.startswith(glob.config.command_prefix) \
            and await commands.process_commands(p, t, msg)

        if cmd and 'resp' in cmd:
            # Command triggered and there is a response to send.
            p.enqueue(await packets.sendMessage(t.name, cmd['resp'], client, t.id))
        else: # No command triggered.
            if match := regexes.now_playing.match(msg):
                # User is /np'ing a map.
                # Save it to their player instance
                # so we can use this elsewhere owo..
                p.last_np = await Beatmap.from_bid(int(match['bid']))

                # Since this is a DM to the bot, we should
                # send back a list of general PP values.
                # TODO: !acc and !mods in commands to
                #       modify these values :P
                msg = 'PP Values: ' + ' | '.join(
                    f'{acc}%: {pp:.2f}pp'
                    for acc, pp in zip(
                        (90, 95, 98, 99, 100),
                        p.last_np.pp_values
                    )) if p.last_np else 'Could not find map.'

                p.enqueue(await packets.sendMessage(t.name, msg, client, t.id))

    else: # Not Aika
        t.enqueue(await packets.sendMessage(client, msg, target, client_id))

    await plog(f'{p} @ {t}: {msg}', Ansi.CYAN, fd = 'logs/chat.log')

# PacketID: 29
@bancho_packet(Packet.c_partLobby)
async def lobbyPart(p: Player, pr: PacketReader) -> None:
    p.in_lobby = False

# PacketID: 30
@bancho_packet(Packet.c_joinLobby)
async def lobbyJoin(p: Player, pr: PacketReader) -> None:
    p.in_lobby = True

    for m in filter(lambda m: m is not None, glob.matches):
        p.enqueue(await packets.newMatch(m))

# PacketID: 31
@bancho_packet(Packet.c_createMatch)
async def matchCreate(p: Player, pr: PacketReader) -> None:
    m, = await pr.read(osuTypes.match)

    m.host = p
    await p.join_match(m, m.passwd)
    await plog(f'{p} created a new multiplayer match.')

# PacketID: 32
@bancho_packet(Packet.c_joinMatch)
async def matchJoin(p: Player, pr: PacketReader) -> None:
    m_id, passwd = await pr.read(osuTypes.i32, osuTypes.string)
    if m_id not in range(64):
        return

    if not (m := glob.matches.get_by_id(m_id)):
        await plog(f'{p} tried to join a non-existant mp lobby?')
        return

    await p.join_match(m, passwd)

# PacketID: 33
@bancho_packet(Packet.c_partMatch)
async def matchPart(p: Player, pr: PacketReader) -> None:
    await p.leave_match()

# PacketID: 38
@bancho_packet(Packet.c_matchChangeSlot)
async def matchChangeSlot(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried changing slot outside of a match?')
        return

    # Read new slot ID
    slot_id, = await pr.read(osuTypes.i32)
    if slot_id not in range(16):
        return

    if m.slots[slot_id].status & SlotStatus.has_player:
        await plog(f'{p} tried to switch to slot {slot_id} which has a player.')
        return

    # Swap with current slot.
    s = m.get_slot(p)
    m.slots[slot_id].copy(s)
    s.reset()
    m.enqueue(await packets.updateMatch(m))

# PacketID: 39
@bancho_packet(Packet.c_matchReady)
async def matchReady(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried readying outside of a match? (1)')
        return

    m.get_slot(p).status = SlotStatus.ready
    m.enqueue(await packets.updateMatch(m))

# PacketID: 40
@bancho_packet(Packet.c_matchLock)
async def matchLock(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried locking a slot outside of a match?')
        return

    # Read new slot ID
    slot_id, = await pr.read(osuTypes.i32)
    if slot_id not in range(16):
        return

    slot = m.slots[slot_id]

    if slot.status & SlotStatus.locked:
        slot.status = SlotStatus.open
    else:
        if slot.player:
            slot.reset()
        slot.status = SlotStatus.locked

    m.enqueue(await packets.updateMatch(m))

# PacketID: 41
@bancho_packet(Packet.c_matchChangeSettings)
async def matchChangeSettings(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried changing multi settings outside of a match?')
        return

    # Read new match data
    new, = await pr.read(osuTypes.match)

    if new.freemods != m.freemods:
        # Freemods status has been changed.
        if new.freemods:
            # Switching to freemods.
            # Central mods -> all players mods.
            for s in m.slots:
                if s.status & SlotStatus.has_player:
                    s.mods = m.mods & ~Mods.SPEED_CHANGING

            m.mods = m.mods & Mods.SPEED_CHANGING
        else:
            # Switching to centralized mods.
            # Host mods -> Central mods.
            for s in m.slots:
                if s.player and s.player.id == m.host.id:
                    m.mods = s.mods | (m.mods & Mods.SPEED_CHANGING)
                    break

    if not new.bmap:
        # Map being changed, unready players.
        for s in m.slots:
            if s.status & SlotStatus.ready:
                s.status = SlotStatus.not_ready
    elif not m.bmap:
        # New map has been chosen, send to match chat.
        await m.chat.send(glob.bot, f'Map selected: {new.bmap.embed}.')

    # Copy basic match info into our match.
    m.bmap = new.bmap
    m.freemods = new.freemods
    m.game_mode = new.game_mode
    m.team_type = new.team_type
    m.match_scoring = new.match_scoring
    m.name = new.name

    m.enqueue(await packets.updateMatch(m))

# PacketID: 44
@bancho_packet(Packet.c_matchStart)
async def matchStart(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried starting match outside of a match?')
        return

    for s in m.slots:
        if s.status & SlotStatus.ready:
            s.status = SlotStatus.playing

    m.in_progress = True
    m.enqueue(await packets.matchStart(m))

# PacketID: 48
@bancho_packet(Packet.c_matchScoreUpdate)
async def matchScoreUpdate(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} sent a scoreframe outside of a match?')
        return

    # Read 37 bytes if using scorev2,
    # otherwise only read 29 bytes.
    size = 37 if pr.data[28] else 29
    data = pr.data[:size]
    data[4] = m.get_slot_id(p)

    m.enqueue(b'0\x00\x00' + size.to_bytes(4, 'little') + data, lobby = False)
    pr.ignore(size)

# PacketID: 49
@bancho_packet(Packet.c_matchComplete)
async def matchComplete(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} sent a scoreframe outside of a match?')
        return

    m.get_slot(p).status = SlotStatus.complete

    all_completed = True

    for s in m.slots:
        if s.status & SlotStatus.playing:
            all_completed = False
            break

    if all_completed:
        m.in_progress = False
        m.enqueue(await packets.matchComplete())

        for s in m.slots: # Reset match statuses
            if s.status == SlotStatus.complete:
                s.status = SlotStatus.not_ready

# PacketID: 51
@bancho_packet(Packet.c_matchChangeMods)
async def matchChangeMods(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried changing multi mods outside of a match?')
        return

    mods, = await pr.read(osuTypes.i32)

    if m.freemods:
        if p.id == m.host.id:
            # Allow host to change speed-changing mods.
            m.mods = mods & Mods.SPEED_CHANGING

        # Set slot mods
        m.get_slot(p).mods = mods & ~Mods.SPEED_CHANGING
    else:
        # Not freemods, set match mods.
        m.mods = mods

    m.enqueue(await packets.updateMatch(m))

# PacketID: 52
@bancho_packet(Packet.c_matchLoadComplete)
async def matchLoadComplete(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} sent a scoreframe outside of a match?')
        return

    # Ready up our player.
    m.get_slot(p).loaded = True

    # Check if all players are ready.
    if not any(s.status & SlotStatus.playing and not s.loaded for s in m.slots):
        m.enqueue(await packets.matchAllPlayerLoaded(), lobby = False)

# PacketID: 54
@bancho_packet(Packet.c_matchNoBeatmap)
async def matchNoBeatmap(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        return

    m.get_slot(p).status = SlotStatus.no_map
    m.enqueue(await packets.updateMatch(m))

# PacketID: 55
@bancho_packet(Packet.c_matchNotReady)
async def matchNotReady(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried unreadying outside of a match? (1)')
        return

    m.get_slot(p).status = SlotStatus.not_ready
    m.enqueue(await packets.updateMatch(m), lobby = False)

# PacketID: 56
@bancho_packet(Packet.c_matchFailed)
async def matchFailed(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        return

    m.enqueue(await packets.matchPlayerFailed(m.get_slot_id(p)))

# PacketID: 59
@bancho_packet(Packet.c_matchHasBeatmap)
async def matchHasBeatmap(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        return

    m.get_slot(p).status = SlotStatus.not_ready
    m.enqueue(await packets.updateMatch(m))

# PacketID: 60
@bancho_packet(Packet.c_matchSkipRequest)
async def matchSkipRequest(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried unreadying outside of a match? (1)')
        return

    m.get_slot(p).skipped = True
    m.enqueue(await packets.matchPlayerSkipped(p.id))

    for s in m.slots:
        if s.status & SlotStatus.playing and not s.skipped:
            return

    # All users have skipped, enqueue a skip.
    m.enqueue(await packets.matchSkip(), lobby = False)

# PacketID: 63
@bancho_packet(Packet.c_channelJoin)
async def channelJoin(p: Player, pr: PacketReader) -> None:
    chan_name, = await pr.read(osuTypes.string)
    c = glob.channels.get(chan_name)

    if not c or not await p.join_channel(c):
        await plog(f'{p} failed to join {chan_name}.', Ansi.YELLOW)
        return

    # Enqueue new channelinfo (playercount) to a ll players.
    #glob.players.enqueue(await packets.channelInfo(*c.basic_info))

    # Enqueue channelJoin to our player.
    p.enqueue(await packets.channelJoin(c.name))

# PacketID: 68
#@bancho_packet(Packet.c_beatmapInfoRequest)
#async def beatmapInfoRequest(p: Player, pr: PacketReader) -> None:
#    req: BeatmapInfoRequest
#    req, = await pr.read(osuTypes.mapInfoRequest)
#
#    info_list = []
#
#    # Filenames
#    for fname in req.filenames:
#        # Attempt to regex pattern match the filename.
#        # If there is no match, simply ignore this map.
#        # XXX: Sometimes a map will be requested without a
#        # diff name, not really sure how to handle this? lol
#        if not (r := regexes.mapfile.match(fname)):
#            continue
#
#        res = await glob.db.fetch(
#            'SELECT id, set_id, status, md5 '
#            'FROM maps WHERE artist = %s AND '
#            'title = %s AND creator = %s AND '
#            'version = %s', [
#                r['artist'], r['title'],
#                r['creator'], r['version']
#            ]
#        )
#
#        if not res:
#            continue
#
#        to_osuapi_status = lambda s: {
#            0: 0,
#            2: 1,
#            3: 2,
#            4: 3,
#            5: 4
#        }[s]
#
#        info_list.append(BeatmapInfo(
#            0, res['id'], res['set_id'], 0,
#            to_osuapi_status(res['status']),
#
#            # TODO: best grade letter rank
#            # the order of these doesn't follow
#            # gamemode ids in osu! either.
#            # (std, ctb, taiko, mania)
#            Rank.N, Rank.N, Rank.N, Rank.N,
#
#            res['md5']
#        ))
#
#    # Ids
#    for m in req.ids:
#        breakpoint()
#
#    p.enqueue(await packets.beatmapInfoReply(info_list))

# PacketID: 70
@bancho_packet(Packet.c_matchTransferHost)
async def matchTransferHost(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried transferring host of a match? (1)')
        return

    # Read new slot ID
    slot_id, = await pr.read(osuTypes.i32)
    if slot_id not in range(16):
        return

    if not (t := m[slot_id].player):
        await plog(f'{p} tried to transfer host to an empty slot?')
        return

    m.host = t
    m.host.enqueue(await packets.matchTransferHost())
    m.enqueue(await packets.updateMatch(m), lobby = False)

# PacketID: 73
@bancho_packet(Packet.c_friendAdd)
async def friendAdd(p: Player, pr: PacketReader) -> None:
    user_id, = await pr.read(osuTypes.i32)

    if not (t := await glob.players.get_by_id(user_id)):
        await plog(f'{t} tried to add a user who is not online! ({user_id})')
        return

    if t.id in (1, p.id):
        # Trying to add the bot, or themselves.
        # These are already appended to the friends list
        # on login, so disallow the user from *actually*
        # editing these in the DB.
        return

    await p.add_friend(t)

# PacketID: 74
@bancho_packet(Packet.c_friendRemove)
async def friendRemove(p: Player, pr: PacketReader) -> None:
    user_id, = await pr.read(osuTypes.i32)

    if not (t := await glob.players.get_by_id(user_id)):
        await plog(f'{t} tried to remove a user who is not online! ({user_id})')
        return

    if t.id in (1, p.id):
        # Trying to remove the bot, or themselves.
        # These are already appended to the friends list
        # on login, so disallow the user from *actually*
        # editing these in the DB.
        return

    await p.remove_friend(t)

# PacketID: 77
@bancho_packet(Packet.c_matchChangeTeam)
async def matchChangeTeam(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried changing team outside of a match? (1)')
        return

    for s in m.slots:
        if p == s.player:
            s.team = Teams.blue if s.team != Teams.blue else Teams.red
            break
    else:
        await plog(f'{p} tried changing team outside of a match? (2)')
        return

    m.enqueue(await packets.updateMatch(m), lobby = False)

# PacketID: 78
@bancho_packet(Packet.c_channelPart)
async def channelPart(p: Player, pr: PacketReader) -> None:
    chan, = await pr.read(osuTypes.string)

    if not chan:
        return

    if not (c := glob.channels.get(chan)):
        await plog(f'Failed to find channel {chan} that {p} attempted to leave.')
        return

    if p not in c:
        # User not in channel.
        return

    # Leave the channel server-side.
    await p.leave_channel(c)

    # Enqueue new channelinfo (playercount) to all players.
    glob.players.enqueue(await packets.channelInfo(*c.basic_info))

# PacketID: 79
@bancho_packet(Packet.c_ReceiveUpdates)
async def receiveUpdates(p: Player, pr: PacketReader) -> None:
    val, = await pr.read(osuTypes.i32)

    if val not in range(3):
        await plog(f'{p} tried to set his presence filter to {val}?')
        return

    p.pres_filter = PresenceFilter(val)

# PacketID: 82
@bancho_packet(Packet.c_setAwayMessage)
async def setAwayMessage(p: Player, pr: PacketReader) -> None:
    pr.ignore(3) # why does first string send \x0b\x00?
    p.away_msg, = await pr.read(osuTypes.string)
    pr.ignore(4)

# PacketID: 85
@bancho_packet(Packet.c_userStatsRequest)
async def statsRequest(p: Player, pr: PacketReader) -> None:
    if len(pr.data) < 6:
        return

    userIDs = await pr.read(osuTypes.i32_list)
    is_online = lambda o: o in glob.players.ids and o != p.id

    for online in filter(is_online, userIDs):
        if t := await glob.players.get_by_id(online):
            p.enqueue(await packets.userStats(t))

# PacketID: 87
@bancho_packet(Packet.c_matchInvite)
async def matchInvite(p: Player, pr: PacketReader) -> None:
    if not p.match:
        await plog(f"{p} tried to invite someone to a match but isn't in one!")
        pr.ignore(4)
        return

    user_id, = await pr.read(osuTypes.i32)
    if not (t := await glob.players.get_by_id(user_id)):
        await plog(f'{t} tried to invite a user who is not online! ({user_id})')
        return

    inv = f'Come join my game: {p.match.embed}.'
    t.enqueue(await packets.sendMessage(p.name, inv, t.name, p.id))
    await plog(f'{p} invited {t} to their match.')

# PacketID: 90
@bancho_packet(Packet.c_matchChangePassword)
async def matchChangePassword(p: Player, pr: PacketReader) -> None:
    if not (m := p.match):
        await plog(f'{p} tried changing match passwd outside of a match?')
        return

    # Read new match data
    new, = await pr.read(osuTypes.match)

    m.passwd = new.passwd
    m.enqueue(await packets.updateMatch(m), lobby=False)

# PacketID: 97
@bancho_packet(Packet.c_userPresenceRequest)
async def userPresenceRequest(p: Player, pr: PacketReader) -> None:
    for pid in await pr.read(osuTypes.i32_list):
        if t := await glob.players.get_by_id(pid):
            p.enqueue(await packets.userPresence(t))

# PacketID: 99
@bancho_packet(Packet.c_userToggleBlockNonFriendPM)
async def toggleBlockingDMs(p: Player, pr: PacketReader) -> None:
    p.pm_private = (await pr.read(osuTypes.i32))[0] == 1
