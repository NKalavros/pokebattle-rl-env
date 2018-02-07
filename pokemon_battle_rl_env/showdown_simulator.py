from json import loads

import websocket
from requests import post

from pokemon_battle_rl_env.battle_simulator import BattleSimulator

WEB_SOCKET_URL = "wss://sim.smogon.com/showdown/websocket"
SHOWDOWN_ACTION_URL = "https://play.pokemonshowdown.com/action.php"


class ShowdownSimulator(BattleSimulator):
    def __init__(self):
        print('Using Showdown')
        self.ws = websocket.WebSocket(sslopt={'check_hostname': False})
        self.ws.connect(WEB_SOCKET_URL)
        print('Connected')
        msg = ''
        while not msg.startswith('|challstr|'):
            msg = self.ws.recv()
        challstr = msg.split('|')[1]
        with open('auth.txt', 'r') as file:
            self.username, self.password = file.readlines()
        self._authenticate(challstr)
        self.ws.send('|/utm null')  # Team
        self.ws.send('|/search gen7randombattle')  # Tier
        msg = ''
        while '|init|battle' not in msg:
            msg = self.ws.recv()
        self.room_id = msg.split('\n')[0][1:]
        msg = ''
        self.opponent = self.username
        while self.opponent == self.username:
            while '|player|' not in msg:
                msg = self.ws.recv()
                print(msg)
            self.opponent = msg.split('|')[3]

        print(f'Playing against {self.opponent}')

        self.ws.send(f'{self.room_id}|/timer on')

        super().__init__()

    def _authenticate(self, challstr):
        post_data = {'act': 'login', 'name': self.username, 'pass': self.password, 'challstr': challstr}
        response = post('http://play.pokemonshowdown.com/action.php', data=post_data)
        assertion = loads(response.text[1:])['assertion']
        login_cmd = f'|/trn {self.username},0,{assertion}'
        self.ws.send(login_cmd)
        msg = ''
        while not msg.startswith('updateuser') and self.username in msg:
            msg = self.ws.recv()

    def attack(self, move):
        self.ws.send(f'|/choose move {move}')

    def switch(self, pokemon):
        pass

    def render(self, mode='human'):
        if mode is 'human':
            raise NotImplementedError  # Open https://play.pokemonshowdown.com in browser

    def reset(self):
        self.ws.send('|/forfeit')

    def close(self):
        self.ws.close()
        print('Connection closed')
