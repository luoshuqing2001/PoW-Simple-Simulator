"""
  Selfish Mining Simulator
"""

from time import *
import datetime
import random
from hashlib import sha256
from copy import deepcopy
from threading import Thread, Lock, Event
from queue import Queue
import os
import shutil  
from pathlib import Path

ratio = 0.3

max_hash_times = 10000
hash_difficulty = 3
num_node = 10
num_attack = int(num_node * ratio) 
channel = {} # (id, queue)
sv_channel = {} # supervision channel, honest nodes communicate with malicious nodes
node_list = []
thread_list = []
receive_list = []
sv_list = []
max_block_num = 40

event_list = []
sv_event_list = []
lock_list = []
update_list = []

lock = Lock() # lock for channel
sv_lock = Lock() # lock for supervision channel

global selfish_mine
selfish_mine = 0
selfish_lock = Lock()

global selfish_start
global selfish_end
selfish_start = 0
selfish_end = 0

class Block:
    """
      Definition of block in blockchain
    """
    def __init__(self, transaction, source_id, timestamp='', prev_hash='') -> None:
        self.nounce = 0
        self.timestamp = timestamp
        self.transaction = transaction
        self.prev_hash = prev_hash
        self.current_hash = self.one_hash()
        self.source_id = source_id
        
    def one_hash(self):
        """
          Compute one hash
        """
        data = f'{self.timestamp}{self.transaction}{self.prev_hash}{self.nounce}'
        return sha256(data.encode()).hexdigest()
      
    def valid_proof(self):
        """
          Compute whether current block is a qualified proof
        """
        return self.current_hash.startswith('0' * hash_difficulty)

class Message:
    """
      Definition of message (in message queue)
    """
    def __init__(self, source_id, chain) -> None:
        self.source_id = source_id
        self.chain = chain

class Node:
    """
      Definition of the behavior for one node
    """
    def __init__(self, id) -> None:
        self.id = id
        self.mine_chain = []
        self.consensus_chain = [Block("genesis", -1)]
        self.flag = False # whether chain has been updated
    
    def valid_chain(self, chain):
        for i in range(len(chain)):
            current_block = chain[i]
            # Exclude some error cases
            if i > 0 and current_block.prev_hash != chain[i-1].current_hash:
                return False
            if current_block.current_hash != current_block.one_hash():
                return False
            if current_block.nounce > max_hash_times:
                return False
            if i > 0 and not current_block.current_hash.startswith('0' * hash_difficulty):
                return False
        return True
    
    def broadcast(self):
        """
          Broadcast current node within the system
        """
        global selfish_mine
        msg = Message(self.id, self.mine_chain)
        selfish_lock.acquire()
        tmp = selfish_mine
        selfish_lock.release()
        # case 1: malicious nodes communicate with each other while selfish mining
        if tmp == 1 and self.id < num_attack:
            lock.acquire()
            for id, que in channel.items():
                if id < num_attack:
                    que.put(msg)
            lock.release()
            for i in range(num_attack):
                event_list[i].set()
        # case 2: honest nodes send message to malicious nodes and honest nodes communicate with each other while selfish mining
        elif tmp == 1 and self.id >= num_attack:
            lock.acquire()
            for id, que in channel.items():
                if id >= num_attack:
                    que.put(msg)
            lock.release()
            for i in range(num_attack, num_node):
                event_list[i].set()
        # case 3: selfish mining is not ongoing
        else:
            lock.acquire()
            for id, que in channel.items():
                que.put(msg)
            lock.release()
            for i in range(num_node):
                event_list[i].set()

    def run(self):
        """
          Node runing function
        """
        global selfish_mine
        global log_handle
        global selfish_start
        while True:
            if len(self.consensus_chain) > max_block_num:
                return
            transaction = str(datetime.datetime.now())
            block = Block(transaction, self.id, str(datetime.datetime.now()), self.consensus_chain[-1].current_hash)
            for i in range(max_hash_times):
                lock_list[self.id].acquire()
                self_flag = self.flag
                lock_list[self.id].release()
                if self_flag == True:
                    lock_list[self.id].acquire()
                    self.flag = False
                    lock_list[self.id].release()
                    break
                block.current_hash = block.one_hash()
                if block.valid_proof():
                    self.mine_chain = self.consensus_chain 
                    self.mine_chain.append(block)
                    print("Node {} mined a new block".format(self.id))
                    selfish_lock.acquire()
                    tmp = selfish_mine
                    selfish_lock.release()
                    if tmp == 0 and self.id < num_attack:
                        selfish_lock.acquire()
                        selfish_mine = 1
                        selfish_lock.release()
                        print("Selfish mining begin at {} in node {}".format(str(datetime.datetime.now()), self.id))
                        selfish_start = len(self.consensus_chain)
                    self.broadcast()
                    break
                else:
                    block.nounce = 1 + i
    
    def receive(self):
        """
          Definition of receive thread
        """
        # global end_flag
        while True:
            if len(self.consensus_chain) > max_block_num:
                return
            event_list[self.id].wait()
            # update its chain
            max_len_chain = 0
            max_chain_copy = []
            max_chain_sender = 0
            while not channel[self.id].empty():
                msg = channel[self.id].get()
                if self.valid_chain(msg.chain) and len(msg.chain) > max_len_chain:
                    max_len_chain = len(msg.chain)
                    max_chain_copy = msg.chain
                    max_chain_sender = msg.source_id
            if max_len_chain > len(self.consensus_chain):
                self.consensus_chain = deepcopy(max_chain_copy)
                lock_list[self.id].acquire()
                self.flag = True
                lock_list[self.id].release()
                selfish_lock.acquire()
                tmp = selfish_mine
                selfish_lock.release()
                if tmp == 1 and self.id >= num_attack:
                    sv_msg = Message(self.id, self.mine_chain)
                    sv_lock.acquire()
                    for id, que in sv_channel.items():
                        que.put(sv_msg)
                    sv_lock.release()
                    for i in range(num_attack):
                        sv_event_list[i].set()
                print("Consensus: node {} update its chain from {}, with len {}"
                      .format(self.id, max_chain_sender, len(self.consensus_chain)))
            
    def supervise(self):
        """
          Malicious nodes use this thread to receive from honest nodes
        """
        global selfish_mine
        global selfish_end
        while True:
            if len(self.consensus_chain) > max_block_num:
                return
            sv_event_list[self.id].wait()
            max_len_chain = 0
            while not sv_channel[self.id].empty():
                msg = sv_channel[self.id].get()
                if self.valid_chain(msg.chain) and len(msg.chain) > max_len_chain:
                    max_len_chain = len(msg.chain)
                selfish_lock.acquire()
                tmp = selfish_mine
                selfish_lock.release()
                if max_len_chain != 0 and max_len_chain < len(self.consensus_chain) and tmp == 1:
                    selfish_lock.acquire()
                    selfish_mine = 0
                    selfish_lock.release()
                    self.mine_chain = self.consensus_chain
                    self.broadcast()
                    print("Selfish mining end!")
                    selfish_end = len(self.consensus_chain)

def main():  
    global selfish_start
    global selfish_end
    
    dir_str = "./data/task_2/node_" + str(num_node) + "_attack_" + str(num_attack) + "_block_" + str(max_block_num) + "/"
    my_file = Path(dir_str)
    if my_file.exists():
        shutil.rmtree(dir_str)
    os.mkdir(dir_str)
    
    log_str = dir_str + "log.txt"
    
    for i in range(num_node):
        node_list.append(Node(i))
        channel[i] = Queue()
        event_list.append(Event())
        lock_list.append(Lock())
        update_list.append(Lock())
    
    for i in range(num_attack):
        sv_event_list.append(Event())
        sv_channel[i] = Queue()
    
    for i in range(num_node):
        thread_list.append(Thread(target=node_list[i].run))
        receive_list.append(Thread(target=node_list[i].receive))
        thread_list[i].daemon = 1
        thread_list[i].start()
        receive_list[i].daemon = 1
        receive_list[i].start()
    
    for i in range(num_attack):
        sv_list.append(Thread(target=node_list[i].supervise))
        sv_list[i].daemon = 1
        sv_list[i].start()
    
    for i in range(num_node):
        thread_list[i].join()
        receive_list[i].join()
    
    for i in range(num_attack):
        sv_list[i].join()
    
    for i in range(num_node):
        mystr = dir_str + str(i + 1) + ".txt"
        file_handle = open(mystr, mode="w")
        counter = 0
        for block in node_list[i].consensus_chain:
            file_handle.write("Node {}, Block {}, Nounce {}, Source Id {}, time stamp {}\n".format(i, counter, block.nounce, block.source_id, block.timestamp))
            counter = counter + 1
        file_handle.close()

    consensus_num = 0
    
    for i in range(max_block_num):
        tmp_nounce = node_list[num_attack].consensus_chain[i].nounce
        tmp_source = node_list[num_attack].consensus_chain[i].source_id
        tmp_flag = False
        for j in range(num_attack, num_node):
            if node_list[j].consensus_chain[i].nounce != tmp_nounce or node_list[j].consensus_chain[i].source_id != tmp_source:
                tmp_flag = True
        if tmp_flag == False:
            consensus_num = consensus_num + 1
    mystr = dir_str + "result.txt"
    file_handle = open(mystr, mode="w")
    file_handle.write("Consensus within honest nodes:\n")
    file_handle.write("Consensus length: {}, total length: {}\n".format(consensus_num, max_block_num))
    
    honest_profit = 0
    malicious_profit = 0
    
    for i in range(1, consensus_num):
        if node_list[num_attack].consensus_chain[i].source_id >= num_attack:
            honest_profit += 1
        else:
            malicious_profit += 1
    file_handle.write("Honest nodes earn {}, with percentage {}, honest nodes account for {}\n".format(honest_profit, honest_profit / (consensus_num - 1), 1 - num_attack / num_node))
    file_handle.write("Malicious nodes earn {}, with percentage {}, malicious nodes account for {}\n".format(malicious_profit, malicious_profit / (consensus_num - 1), num_attack / num_node))
    file_handle.write("Selfish mining begin at {}, end at {}, with length {}\n".format(selfish_start, selfish_end, selfish_end - selfish_start))

    file_handle.close()

    print("Over!")


if __name__ == '__main__':
    main()