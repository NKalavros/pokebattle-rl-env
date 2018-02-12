from json import loads
from os.path import isfile
from secrets import choice
from string import ascii_letters, digits

from requests import post
from websocket import WebSocket

from pokebattle_rl_env.battle_simulator import BattleSimulator
from pokebattle_rl_env.game_state import GameState, Move

WEB_SOCKET_URL = "wss://sim.smogon.com/showdown/websocket"
SHOWDOWN_ACTION_URL = "https://play.pokemonshowdown.com/action.php"


def register(challstr, username, password):
    post_data = {
        'act': 'register',
        'captcha': 'pikachu',
        'challstr': challstr,
        'cpassword': password,
        'password': password,
        'username': username
    }
    response = post(SHOWDOWN_ACTION_URL, data=post_data)
    if response.text[0] != ']':
        raise AttributeError('Invalid username and/or password')
    response = loads(response.text[1:])
    if not response['actionsuccess']:
        raise AttributeError('Invalid username and/or password')
    return response['assertion']


def login(challstr, username, password):
    post_data = {'act': 'login', 'name': username, 'pass': password, 'challstr': challstr}
    response = post(SHOWDOWN_ACTION_URL, data=post_data)
    response = loads(response.text[1:])
    return response['assertion']


def auth_temp_user(challstr, username):
    post_data = {'act': 'getassertion', 'challstr': challstr, 'userid': username}
    response = post(SHOWDOWN_ACTION_URL, data=post_data)
    return response.text


def generate_username():
    return generate_token(8)


def generate_token(length):
    return ''.join(choice(ascii_letters + digits) for i in range(length))


def parse_pokemon_details(details):
    species = details.split(',')[0]
    if ', M' in details:
        gender = 'm'
    elif ', F' in details:
        gender = 'f'
    else:
        gender = 'n'
    return species, gender


def parse_move(info, state, opponent_short):
    if opponent_short in info[2]:
        move_name = info[3]
        pokemon = state.opponent.pokemon
        used_move = next((m for m in pokemon[0].moves if m.name == move_name), None)
        if not used_move:
            used_move = Move(name=move_name)
            pokemon[0].moves.append(used_move)


def parse_switch(info, state, opponent_short):
    name = info[2].split(':')[1][1:]
    species = info[3].split(',')[0]
    if opponent_short in info[2]:
        pokemon = state.opponent.pokemon
        if ', M' in info[3]:
            gender = 'm'
        elif ', F' in info[3]:
            gender = 'f'
        else:
            gender = 'n'
        health, max_health, status = parse_health_status(info[4])
        switched_in = next((p for p in pokemon if p.species == species or p.name == name), None)
        if switched_in is None:
            first_unknown = next(p for p in pokemon if p.unknown)
            first_unknown.unknown = False
            switched_in = first_unknown
        switched_in.name = name
        switched_in.species = species
        switched_in.gender = gender
        switched_in.health = health
        switched_in.max_health = max_health if max_health is not None else 100
        if status not in switched_in.conditions:
            switched_in.conditions.append(status)
        switched_in.update()
    else:
        pokemon = state.player.pokemon
        switched_in = next((p for p in pokemon if p.species == species or p.name == name), None)
    pokemon.insert(0, pokemon.pop(pokemon.index(switched_in)))


def sanitize_hidden_power(move_id):
    if move_id.startswith('hiddenpower') and move_id.endswith('60'):
        move_id = move_id[:-2]
    return move_id


def parse_health_status(string):
    condition = None
    max_health = None
    if ' ' in string:
        health, condition = string.split(' ')
    else:
        health = string
    if '/' in health:
        health, max_health = health.split('/')
    return float(health), float(max_health) if max_health is not None else None, condition


def read_state_json(json, state):
    json = loads(json)
    st_active_pokemon = state.player.pokemon[0]
    st_active_pokemon.moves = []
    active_pokemon = json['active'][0]
    if 'trapped' in active_pokemon:
        st_active_pokemon.trapped = active_pokemon['trapped']
        enabled_move_id = next(iter(active_pokemon['moves'].values()))['id']
        for move in st_active_pokemon.moves:
            move.disabled = not move.id == enabled_move_id
    else:
        st_active_pokemon.trapped = False
        for move in active_pokemon['moves']:
            move_id = move['id']
            move_id = sanitize_hidden_power(move_id)
            move = Move(id=move_id, pp=move['pp'], disabled=move['disabled'])
            st_active_pokemon.moves.append(move)
    pokemon_list = json['side']['pokemon']
    for i in range(len(pokemon_list)):
        st_pokemon = state.player.pokemon[i]
        pokemon = pokemon_list[i]
        st_pokemon.name = pokemon['ident'].split(':')[1][1:]
        st_pokemon.species, st_pokemon.gender = parse_pokemon_details(pokemon['details'])
        health, max_health, status = parse_health_status(pokemon['condition'])
        if max_health is not None:
            st_pokemon.max_health = max_health
        st_pokemon.health = health
        st_pokemon.conditions = [status]
        st_pokemon.stats = pokemon['stats']
        if not pokemon['active'] and not all(
                move_id in [move.name for move in st_pokemon.moves] for move_id in pokemon['moves']):
            st_pokemon.moves = [Move(id=sanitize_hidden_power(move_id)) for move_id in pokemon['moves']]
        st_pokemon.item = pokemon['item']
        st_pokemon.ability = pokemon['ability']
        st_pokemon.unknown = False


class ShowdownSimulator(BattleSimulator):
    def __init__(self, auth=''):
        print('Using Showdown backend')
        self._connect(auth)
        print(f'Using username {self.username} with password {self.password}')
        self.ws.send('|/utm null')  # Team
        self.state = GameState()
        self.room_id = None
        super().__init__()

    def _connect(self, auth):
        self.ws = WebSocket(sslopt={'check_hostname': False})
        self.ws.connect(url=WEB_SOCKET_URL)
        print('Connected')
        msg = ''
        while not msg.startswith('|challstr|'):
            msg = self.ws.recv()
        challstr = msg[msg.find('|challstr|') + len('|challstr|'):]
        if auth == 'register':
            self.username = generate_username()
            self.password = generate_token(16)
            assertion = register(challstr=challstr, username=self.username, password=self.password)
        elif isfile(auth):
            with open(auth, 'r') as file:
                self.username, password = file.read().splitlines()
                self.password = None
            assertion = login(challstr=challstr, username=self.username, password=password)
        else:
            self.username = generate_username()
            self.password = None
            assertion = auth_temp_user(challstr=challstr, username=self.username)
        login_cmd = f'|/trn {self.username},0,{assertion}'
        self.ws.send(login_cmd)
        msg = ''
        while not msg.startswith('|updateuser|') and self.username not in msg:
            print(msg)
            msg = self.ws.recv()

    def _attack(self, move):
        self.ws.send(f'{self.room_id}|/move {move}')

    def _switch(self, pokemon):
        self.ws.send(f'{self.room_id}|/switch {pokemon}')

    def _update_state(self):
        end = False
        while not end:
            msg = self.ws.recv()
            end = self._parse_message(msg)

    def _parse_message(self, msg):
        if self.room_id is None and '|init|battle' in msg:
            self.room_id = msg.split('\n')[0][1:]
        end = False
        if not msg.startswith(f'>{self.room_id}'):
            return False
        print(msg)
        msgs = msg.split('\n')
        for msg in msgs:
            info = msg.split('|')
            if len(info) < 2:
                continue
            if info[1] == 'player':
                if info[3] == self.username:
                    self.player_short = info[2]
                    self.state.player.name = info[3]
                else:
                    self.opponent = info[3]
                    self.state.opponent.name = self.opponent
                    self.opponent_short = info[2]
            elif info[1] == 'win':
                winner = msg[len('|win|'):]
                self.state.state = 'win' if winner == self.state.player.name else 'loss'
                end = True
            elif info[1] == 'tie':
                self.state.state = 'tie'
                end = True
            elif info[1] == 'turn':
                self.state.turn = int(info[2])
                if self.state.turn == 1:
                    self.state.state = 'ongoing'
                end = True
            elif info[1] == 'request':
                if info[2].startswith('{"forceSwitch":[true]'):
                    self.force_switch = True
                    end = True
                    continue
                if info[2] != '' and not info[2].startswith('{"wait":true'):
                    read_state_json(info[2], self.state)
            elif info[1] == 'move':
                parse_move(info, self.state, self.opponent_short)
            elif info[1] == 'upkeep':
                pass  # ToDo: update weather, status turns
            elif info[1] == 'switch' or info[1] == 'drag':
                parse_switch(info, self.state, self.opponent_short)
            elif info[1] == '-damage':
                if self.opponent_short in info[2]:
                    name = info[2].split(':')[1][1:]
                    damaged = next(p for p in self.state.opponent.pokemon if p.name == name)
                    health, max_health, condition = parse_health_status(info[3])
                    if condition is not None and condition not in damaged.conditions:
                        damaged.conditions.append(condition)
                    if max_health is not None:
                        damaged.max_health = max_health
                    damaged.health = health
            elif info[1] == '-status':
                if self.opponent_short in info[2]:
                    name = info[2].split(':')[1][1:]
                    inflicted = next(p for p in self.state.opponent.pokemon if p.name == name)
                    condition = info[3]
                    if condition not in inflicted.conditions:
                        inflicted.conditions.append(condition)
            elif info[1] == '-curestatus':
                if self.opponent_short in info[2]:
                    name = info[2].split(':')[1][1:]
                    cured = next(p for p in self.state.opponent.pokemon if p.name == name)
                    condition = info[3]
                    if condition in cured.conditions:
                        cured.conditions.remove(condition)
            elif info[1] == '-message':
                if 'lost due to inactivity.' in info[2] or 'forfeited.' in info[2]:
                    self.state.forfeited = True
        return end

    def render(self, mode='human'):
        if mode is 'human':
            raise NotImplementedError  # Open https://play.pokemonshowdown.com in browser

    def reset(self):
        if self.state.state == 'ongoing':
            self.ws.send('|/forfeit')
        if self.room_id is not None:
            self.ws.send(f'|/leave {self.room_id}')
            msg = ''
            while 'deinit' not in msg:
                msg = self.ws.recv()
        self.ws.send('|/search gen7randombattle')  # Tier
        self._update_state()
        print(f'Playing against {self.opponent}')
        self.ws.send(f'{self.room_id}|/timer on')

    def close(self):
        self.ws.close()
        print('Connection closed')
