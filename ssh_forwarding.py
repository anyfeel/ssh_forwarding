#!/usr/bin/env python
# encoding: utf-8

'''
__version__ = "0.01"
__author__ = "Jinzheng Zhang"
__email__ = "tianchaijz@gmail.com"
'''

from __future__ import print_function

import os
import time
import json
import socket

from threading import Thread, Lock
from subprocess import PIPE, Popen

from optparse import OptionParser

INTERVAL = 5
LOCAL_ADDR = '127.0.0.1'


def shell(command, stdin=None):
    process = Popen(
        args=command,
        stdout=PIPE,
        stderr=PIPE,
        stdin=stdin,
        shell=True,
        close_fds=True
    )

    return process


def os_kill(pid):
    if pid is not None:
        shell("kill -9 %s" % pid)


def close_noexcept(fd):
    try:
        fd.close()
    except:
        pass


def terminate_subprocess(proc, msg):
    print("terminate subprocess: %s" % msg)
    close_noexcept(proc.stdin)
    close_noexcept(proc.stdout)
    close_noexcept(proc.stderr)

    try:
        proc.kill()
    except:
        pass
    proc.wait()


def communicate(proc):
    while True:
        try:
            proc.stderr.read()
            proc.stdout.read()
        except Exception as e:
            print("communicate:", e)
            break
        time.sleep(INTERVAL)


class Forwarding(Thread):
    def lock(func):
        def wrapper(*args, **kwargs):
            with args[0].lock:
                return func(*args, **kwargs)
        return wrapper

    def get_tasks(self):
        for l in self.forwarding_list:
            addrs = l.split(':')
            if len(addrs) != 3 and len(addrs) != 4:
                raise(Exception('invalid forwarding list'))

            task = {'forwarding': l, 'down': True}
            if len(addrs) == 3:
                if self.flag == 'L':
                    task['check_addr'], task['check_port'] = \
                        LOCAL_ADDR, addrs[0]

            if len(addrs) == 4:
                task['check_port'] = addrs[1]
                if self.flag == 'L':
                    if addrs[0] == '0.0.0.0':
                        task['check_addr'] = LOCAL_ADDR
                    else:
                        task['check_addr'] = addrs[0]
                if self.flag == 'R':
                    if addrs[0] == '0.0.0.0':
                        task['check_addr'] = self.host

            self.tasks.append(task)

    def __init__(self, cfg):
        self.lock = Lock()

        if cfg['mode'] == 'local' or cfg['mode'] == 'L':
            self.flag = 'L'
        elif cfg['mode'] == 'remote' or cfg['mode'] == 'R':
            self.flag = 'R'
        else:
            raise(Exception('unknown mode'))

        self.timeout = cfg.get('timeout', 2)
        self.close = False

        remote = cfg['remote']
        self.host = remote['host']
        self.user = remote['user']
        self.port = remote.get('port', 22)

        self.tasks, self.forwarding_list = [], cfg['forwarding_list']
        self.get_tasks()

    def __str__(self):
        return json.dumps(self.tasks)

    def run(self):
        print(self)
        try:
            while True and not self.close:
                self.check_status(False)
                time.sleep(INTERVAL)
        except (EOFError):
            return

    def forwarding(self, task):
        ssh_cmd = 'ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=no' \
            ' -{flag}' \
            ' {forwarding}' \
            ' {user}@{host} -p {port}'

        attr = {
            'flag': self.flag,
            'forwarding': task['forwarding'],
            'user': self.user,
            'host': self.host,
            'port': self.port,
        }

        cmd = ssh_cmd.format(**attr)
        task['proc'] = shell(cmd, PIPE)
        Thread(target=communicate, args=(task['proc'],)).start()

    def check_alive(self, task, verbose):
        if not task.get('check_addr'):
            if task.get('proc'):
                try:
                    task['proc'].stdin.write('pwd\n')
                    print("interact ok")
                except IOError:
                    task['down'] = True
                else:
                    task['down'] = False

            return

        addr, port = task['check_addr'], task['check_port']
        msg = None
        try:
            sock = None
            sock = socket.create_connection((addr, int(port)),
                                            self.timeout)
        except socket.error as e:
            msg = e
            task['down'] = True
        else:
            task['down'] = False
            msg = 'success'
        finally:
            if sock:
                sock.close()

        if verbose:
            print("connect %s:%s (%s)" % (addr, port, msg))

    @lock
    def check_status(self, verbose):
        for task in self.tasks:
            self.check_alive(task, verbose)
            if task['down']:
                if task.get('proc'):
                    terminate_subprocess(task['proc'], task['forwarding'])
                self.forwarding(task)

    @lock
    def exit(self):
        self.close = True
        for task in self.tasks:
            if task.get('proc'):
                terminate_subprocess(task['proc'], task['forwarding'])


def check_input(ssh_forwarding):
    while True:
        try:
            raw_input("type ^D to exit\n")
        except (EOFError):
            ssh_forwarding.exit()
            os_kill(os.getpid())
        else:
            ssh_forwarding.check_status(True)


def main():
    parser = OptionParser()
    parser.add_option('-c', dest='config', action="store", type="string",
                      help='Specify the config json file')

    (options, args) = parser.parse_args()
    cfg = json.load(open(options.config))

    ssh_forwarding = Forwarding(cfg)
    Thread(target=check_input, args=(ssh_forwarding,)).start()
    Thread(target=ssh_forwarding.run).start()


if __name__ == '__main__':
    main()
