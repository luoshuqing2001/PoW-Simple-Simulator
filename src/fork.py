"""
  PoW Simulator
"""

from hashlib import sha256
from copy import deepcopy
from threading import Thread, Lock, Event
from queue import Queue
import os
import shutil  
from pathlib import Path
import datetime
import matplotlib.pyplot as plt

ratio = 0.4

max_hash_times = 10000
hash_difficulty = 3
num_node = 10
num_attack = int(num_node * ratio)
channel = {} # (id, queue)
node_list = []
thread_list = []
receive_list = []
max_block_num = 20
event_list = []
lock_list = []
update_list = []

lock = Lock() # lock for channel

global file_handle

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
        data = f'{str(self.timestamp)}{self.transaction}{self.prev_hash}{self.nounce}'
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
        msg = Message(self.id, self.mine_chain)
        if self.id < num_attack:
            lock.acquire()
            for id, que in channel.items():
                if id < num_attack:
                    que.put(msg)
            lock.release()
            for i in range(num_attack):
                event_list[i].set()
        else:
            lock.acquire()
            for id, que in channel.items():
                if id >= num_attack:
                    que.put(msg)
            lock.release()
            for i in range(num_attack, num_node):
                event_list[i].set()


    def run(self):
        """
          Node runing function
        """
        global file_handle
        while True:
            if len(self.consensus_chain) > max_block_num:
                return
            transaction = (datetime.datetime.now())
            block = Block(transaction, self.id, (datetime.datetime.now()), self.consensus_chain[-1].current_hash)
            for i in range(max_hash_times):
                block.current_hash = block.one_hash()
                if block.valid_proof():
                    self.mine_chain = self.consensus_chain 
                    self.mine_chain.append(block)
                    print("Node {} mined a new block".format(self.id))
                    file_handle.write("Node {} mined a new block\n".format(self.id))
                    self.broadcast()
                    break
                else:
                    block.nounce = 1 + i
                    if self.flag == True:
                        lock_list[self.id].acquire()
                        self.flag = False
                        lock_list[self.id].release()
                        break
                    
            
    def receive(self):
        """
          Definition of receive thread
        """
        global file_handle
        max_len_chain = 0
        max_chain_copy = []
        max_chain_sender = 0
        while True:
            if len(self.consensus_chain) > max_block_num:
                return
            event_list[self.id].wait()
            # update its chain
            max_len_chain = 0
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
                print("Consensus: node {} update its chain from {}, with len {}"
                      .format(self.id, max_chain_sender, len(self.consensus_chain)))
                file_handle.write("Consensus: node {} update its chain from {}, with len {}\n"
                                  .format(self.id, max_chain_sender, len(self.consensus_chain)))

def main():
    global file_handle
    dir_str = "./data/task_3/node_" + str(num_node) + "_attack_" + str(ratio) + "/"
    my_file = Path(dir_str)
    if my_file.exists():
        shutil.rmtree(dir_str)
    os.mkdir(dir_str)
    
    mystr = dir_str + "log.txt"
    file_handle = open(mystr, mode="w")
    
    for i in range(num_node):
        node_list.append(Node(i))
        channel[i] = Queue()
        event_list.append(Event())
        lock_list.append(Lock())
        update_list.append(Lock())
    
    for i in range(num_node):
        thread_list.append(Thread(target=node_list[i].run))
        receive_list.append(Thread(target=node_list[i].receive))
        thread_list[i].daemon = 1
        thread_list[i].start()
        receive_list[i].daemon = 1
        receive_list[i].start()
    
    for i in range(num_node):
        thread_list[i].join()
        receive_list[i].join()
    
    for i in range(num_node):
        print("Write start")
        mystr = dir_str + str(i + 1) + ".txt"
        file_handle = open(mystr, mode="w")
        counter = 0
        for block in node_list[i].consensus_chain:
            file_handle.write("Node {}, Block {}, Nounce {}, Source Id {}, time stamp {}\n".format(i, counter, block.nounce, block.source_id, str(block.timestamp)))
            counter = counter + 1
    
    consensus_attack = 0
    consensus_num = 0
    
    for i in range(max_block_num):
        tmp_nounce = node_list[0].consensus_chain[i].nounce
        tmp_source = node_list[0].consensus_chain[i].source_id
        tmp_flag = False
        for j in range(1, num_attack):
            if node_list[j].consensus_chain[i].nounce != tmp_nounce or node_list[j].consensus_chain[i].source_id != tmp_source:
                tmp_flag = True
        if tmp_flag == False:
            consensus_attack += 1
    
        tmp_nounce = node_list[num_attack].consensus_chain[i].nounce
        tmp_source = node_list[num_attack].consensus_chain[i].source_id
        tmp_flag = False
        for j in range(num_attack, num_node):
            if node_list[j].consensus_chain[i].nounce != tmp_nounce or node_list[j].consensus_chain[i].source_id != tmp_source:
                tmp_flag = True
        if tmp_flag == False:
            consensus_num += 1
    
    mystr = dir_str + "result.txt"
    file_handle = open(mystr, mode="w")
    file_handle.write("Consensus length within attack nodes: {}, total length: {}\n".format(consensus_attack, max_block_num))
    file_handle.write("Consensus length within honest nodes: {}, total length: {}\n".format(consensus_num, max_block_num))
    
    start_attack = 0
    start_honest = 0
    
    while True:
        if start_attack + start_honest >= 10:
            break
        if node_list[0].consensus_chain[start_attack + 1].timestamp < node_list[num_attack].consensus_chain[start_honest + 1].timestamp:
            start_attack += 1
        else:
            start_honest += 1
    
    file_handle.write("Attack nodes mined {} blocks, Honest nodes mined {} blocks.\n".format(start_attack, start_honest))
    print("Attack nodes mined {} blocks, Honest nodes mined {} blocks.".format(start_attack, start_honest))
    
    file_handle.close()

if __name__ == '__main__':
    main()