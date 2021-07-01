#!/usr/bin/env python2
# Copyright (c) 2014 The Bitcoin Core developers
# Copyright (c) 2018 The Zencash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
from test_framework.test_framework import BitcoinTestFramework
from test_framework.authproxy import JSONRPCException
from test_framework.util import assert_equal, initialize_chain_clean, \
    start_nodes, sync_blocks, sync_mempools, connect_nodes_bi, mark_logs,\
    get_epoch_data, \
    assert_false, assert_true
from test_framework.mc_test.mc_test import *
import os
import json
import pprint
from decimal import Decimal
import threading
import time
from websocket import create_connection
from websocket._exceptions import WebSocketConnectionClosedException
from test_framework.wsproxy import JSONWSException

DEBUG_MODE = 1
NUMB_OF_NODES = 3
EPOCH_LENGTH = 5
FT_SC_FEE = Decimal('0.0005')
MBTR_SC_FEE = Decimal('0.0004')
CERT_FEE = Decimal('0.00015')
BLOCK_HASH_LIMIT = 100


def ws_client(node, arg):
    wsurl = node.get_wsurl()

    if wsurl == None:
        print "###################### no ws conn: exiting"
        return

    print "##### ws client connecting to ws_url {} ######################".format(wsurl)
    ws = create_connection(wsurl)

    t = threading.currentThread()
    c = 0

    while getattr(t, "do_run", True):
        try:
            data = ws.recv()
            #c += 1
            #print "received data....", c

            if getattr(t, "handle_events", True):
                arg.wsEventPayload = json.loads(data)['eventPayload']
                arg.sem.release()
                print "############ Sem Given"
        except WebSocketConnectionClosedException, e:
            print "############ Server closed connection"
            break
        except Exception, e:
            print "Unexpected exception:  ", str(e)
            break


    print "##### ws client closing".format(wsurl)
    ws.close()

class ws_messages(BitcoinTestFramework):

    alert_filename = None

    def setup_chain(self, split=False):
        print("Initializing test directory " + self.options.tmpdir)
        initialize_chain_clean(self.options.tmpdir, NUMB_OF_NODES)
        self.alert_filename = os.path.join(self.options.tmpdir, "alert.txt")
        with open(self.alert_filename, 'w'):
            pass  # Just open then close to create zero-length file

    def setup_network(self, split=False):
        self.nodes = []

        common_args = [
            '-websocket=1', '-debug=ws',
            '-txindex=1',
            '-debug=py', '-debug=sc', '-debug=mempool', '-debug=net',
            '-debug=cert', '-debug=zendoo_mc_cryptolib', '-logtimemicros=1']

        self.nodes = start_nodes(NUMB_OF_NODES, self.options.tmpdir, extra_args = [common_args]*NUMB_OF_NODES)

#        import pdb; pdb.set_trace()
        connect_nodes_bi(self.nodes, 0, 1)
        connect_nodes_bi(self.nodes, 1, 2)
        sync_blocks(self.nodes[1:NUMB_OF_NODES])
        sync_mempools(self.nodes[1:NUMB_OF_NODES])
        self.is_network_split = split
        self.sync_all()

    def run_test(self):

        '''
        Different Websocket messages are tested
        '''

        self.sem = threading.Semaphore()
        self.sem.acquire()
        print "############ Sem Taken"

        t = threading.Thread(target=ws_client, args=(self.nodes[1], self,))
        t.daemon = True         # This thread dies when main thread exits.
        t.handle_events = False # do not handle evt by default
        t.start()

        # forward transfer amounts
        creation_amount = Decimal("0.5")
        fwt_amount = Decimal("50")
        bwt_amount_bad = Decimal("100.0")
        bwt_amount = Decimal("50")

        self.nodes[0].getblockhash(0)

        # node 1 earns some coins, they would be available after 100 blocks
        mark_logs("Node 1 generates 1 block", self.nodes, DEBUG_MODE)
        self.nodes[1].generate(1)
        self.sync_all()

        mark_logs("Node 0 generates 220 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(220)
        self.sync_all()

        mark_logs("Sending an invalid ws message", self.nodes, DEBUG_MODE)
        try:
            self.nodes[0].ws_test("Hello World!")
            print qqq
        except JSONWSException, e:
            print "############ exception:", e.error
        except Exception, e:
            print "Unexpected exception:  ", str(e)


        # SC creation

        #generate wCertVk and constant
        mcTest = CertTestUtils(self.options.tmpdir, self.options.srcdir)
        vk = mcTest.generate_params("sc1")
        constant = generate_random_field_element_hex()

        ret = self.nodes[1].sc_create(EPOCH_LENGTH, "dada", creation_amount, vk, "", constant)
        creating_tx = ret['txid']
        scid = ret['scid']
        pprint.pprint(scid)
        mark_logs("Node 1 created the SC spending {} coins via tx {}.".format(creation_amount, creating_tx), self.nodes, DEBUG_MODE)
        mark_logs("created SC id: {}".format(scid), self.nodes, DEBUG_MODE)
        self.sync_all()

        mark_logs("Node0 confirms Sc creation generating 1 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        sc_creating_height = self.nodes[0].getblockcount()
        self.sync_all()

        # Fwd Transfer to Sc
        fwd_tx = self.nodes[0].sc_send("abcd", fwt_amount, scid)
        mark_logs("Node0 transfers {} coins to SC with tx {}...".format(fwt_amount, fwd_tx), self.nodes, DEBUG_MODE)
        self.sync_all()

        mark_logs("Node0 confirms fwd transfer generating 1 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        self.sync_all()

        mark_logs("Node0 generating 3 more blocks to achieve end of withdrawal epoch", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(3)
        self.sync_all()

        epoch_number, cum_tree_hash = get_epoch_data(scid, self.nodes[0], EPOCH_LENGTH)
        mark_logs("epoch_number = {}, cumulative_hash = {}".format(epoch_number, cum_tree_hash), self.nodes, DEBUG_MODE)

        pkh_node1 = self.nodes[1].getnewaddress("", True)

        #Create proof for WCert
        quality = 0
        proof = mcTest.create_test_proof(
            "sc1", epoch_number, quality, MBTR_SC_FEE, FT_SC_FEE,
            constant, cum_tree_hash, [pkh_node1], [bwt_amount])

        amount_cert_1 = [{"pubkeyhash": pkh_node1, "amount": bwt_amount}]
        mark_logs("Node 0 performs a bwd transfer to Node1 pkh {} of {} coins via Websocket".format(amount_cert_1[0]["pubkeyhash"], amount_cert_1[0]["amount"]), self.nodes, DEBUG_MODE)
        #----------------------------------------------------------------"
        cert_epoch_0 = self.nodes[1].ws_send_certificate(
            scid, epoch_number, quality, cum_tree_hash, proof, amount_cert_1, FT_SC_FEE, MBTR_SC_FEE, CERT_FEE)
        self.sync_all()

        mark_logs("Check cert is in mempool", self.nodes, DEBUG_MODE)
        assert_equal(True, cert_epoch_0 in self.nodes[0].getrawmempool())

        mined = self.nodes[0].generate(1)[0]
        self.sync_all()

        mark_logs("Check cert is not in mempool anymore", self.nodes, DEBUG_MODE)
        assert_equal(False, cert_epoch_0 in self.nodes[0].getrawmempool())

        mark_logs("Check block coinbase contains the certificate fee", self.nodes, DEBUG_MODE)
        coinbase = self.nodes[0].getblock(mined, True)['tx'][0]
        decoded_coinbase = self.nodes[2].getrawtransaction(coinbase, 1)
        miner_quota = decoded_coinbase['vout'][0]['value']
        assert_equal((Decimal('7.5') + CERT_FEE), miner_quota)
        assert_equal(self.nodes[1].getscinfo(scid)['items'][0]['last ftScFee'], FT_SC_FEE)
        assert_equal(self.nodes[1].getscinfo(scid)['items'][0]['last mbtrScFee'], MBTR_SC_FEE)

        # ----------------------------------------------------------------"
        # Test get single block
        mark_logs("Node0 generates 1 block, check that Websocket evt is correctly handled ", self.nodes, DEBUG_MODE)
        t.handle_events = True
        block_hash = self.nodes[0].generate(1)[0]
        self.sync_all()
        while True:
            self.sem.acquire()
            t.handle_events = False
            print "############ Sem Taken"
            break

        height = self.nodes[0].getblockcount()
        exp_block = self.nodes[0].getblock(str(height), False)
        assert_equal(self.wsEventPayload['height'], height)
        assert_equal(self.wsEventPayload['hash'], block_hash)
        assert_equal(self.wsEventPayload['block'], exp_block)
        print "=====> GotEvent: "
        pprint.pprint(self.wsEventPayload)

        mark_logs("Getting block via ws with block height", self.nodes, DEBUG_MODE)
        height_, hash_, block_ = self.nodes[0].ws_get_single_block(height)
        assert_equal(height, height_)
        assert_equal(block_hash, hash_)
        assert_equal(exp_block, block_)

        mark_logs("Getting block via ws with block hash", self.nodes, DEBUG_MODE)
        height_, hash_, block_ = self.nodes[0].ws_get_single_block(block_hash)
        assert_equal(height, height_)
        assert_equal(block_hash, hash_)
        assert_equal(exp_block, block_)

        # ----------------------------------------------------------------"
        # Test get multiple block hashes
        # On this test start_height and start_hash point to block before created sequence.
        mark_logs("Node0 generates 5 blocks", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        start_hash = self.nodes[0].getblockhash(start_height)
        self.nodes[0].generate(5)[0]
        self.sync_all()

        height = self.nodes[0].getblockcount()
        exp_hashes = [self.nodes[0].getblockhash(n) for n in range(start_height + 1, height + 1)]

        mark_logs("Getting multiple hashes via ws with starting hash", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_multiple_block_hashes(start_hash, 5)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height + 1, height_)

        mark_logs("Getting multiple hashes via ws with starting height", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_multiple_block_hashes(start_height, 5)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height + 1, height_)

        mark_logs("Node0 generates " + str(BLOCK_HASH_LIMIT) +" blocks", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        start_hash = self.nodes[0].getblockhash(start_height)
        self.nodes[0].generate(BLOCK_HASH_LIMIT)[0]
        self.sync_all()

        height = self.nodes[0].getblockcount()
        exp_hashes = [self.nodes[0].getblockhash(n) for n in range(start_height + 1, height + 1)]

        mark_logs("Getting multiple hashes via ws with starting hash", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_multiple_block_hashes(start_hash, BLOCK_HASH_LIMIT)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height + 1, height_)

        mark_logs("Getting multiple hashes via ws with starting height", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_multiple_block_hashes(start_height, BLOCK_HASH_LIMIT)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height + 1, height_)

        try:
            mark_logs("Try to request block hashes over the limit", self.nodes, DEBUG_MODE)
            self.nodes[0].ws_get_multiple_block_hashes(start_hash, BLOCK_HASH_LIMIT + 1)
            raise RuntimeError("Get multiple block hashes. Rquest over the limit(" + str(BLOCK_HASH_LIMIT) +" hashes) passed.")
        except JSONWSException as e:
            print "Exception:", e.error

        try:
            mark_logs("Try to request block hashes over the limit", self.nodes, DEBUG_MODE)
            self.nodes[0].ws_get_multiple_block_hashes(start_height, BLOCK_HASH_LIMIT + 1)
            raise RuntimeError("Get multiple block hashes. Rquest over the limit(" + str(BLOCK_HASH_LIMIT) +" hashes) passed.")
        except JSONWSException as e:
            print "Exception:", e.error

        # ----------------------------------------------------------------"
        # Test get new block hashes
        # On this test start_height and start_hash is the first block of created sequence.
        mark_logs("Node0 generates 5 blocks", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        start_hash = self.nodes[0].generate(5)[0]
        start_height = start_height + 1  # First created block of sequence
        self.sync_all()

        height = self.nodes[0].getblockcount()
        exp_hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height + 1)]

        mark_logs("Getting new block hashes via ws", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_new_block_hashes([start_hash], 5)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height, height_)

        mark_logs("Node0 generates " + str(BLOCK_HASH_LIMIT) +" blocks", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        start_hash = self.nodes[0].generate(BLOCK_HASH_LIMIT)[0]
        start_height = start_height + 1 # First created block of sequence
        self.sync_all()

        height = self.nodes[0].getblockcount()
        exp_hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height + 1)]

        mark_logs("Getting new block hashes via ws", self.nodes, DEBUG_MODE)
        height_,hashes_ = self.nodes[0].ws_get_new_block_hashes([start_hash], BLOCK_HASH_LIMIT)
        assert_equal(exp_hashes, hashes_)
        assert_equal(start_height, height_)

        try:
            mark_logs("Try to request block hashes over the limit", self.nodes, DEBUG_MODE)
            self.nodes[0].ws_get_new_block_hashes([start_hash], BLOCK_HASH_LIMIT + 1)
            raise RuntimeError("New block hashes. Rquest over the limit(" + str(BLOCK_HASH_LIMIT) +" hashes) passed.")
        except JSONWSException as e:
            print "Exception:", e.error

        mark_logs("Test for retrieving 1 header", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        self.nodes[0].generate(1)
        height = self.nodes[0].getblockcount()
        exp_headers = [self.nodes[0].getblock(str(start_height), False)[0:354]]
        hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height)]
        headers_ = self.nodes[0].ws_get_block_headers(hashes)
        assert_equal(exp_headers, headers_)

        mark_logs("Test for retrieving 10 headers", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        self.nodes[0].generate(10)
        height = self.nodes[0].getblockcount()
        hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height)]
        exp_headers = [self.nodes[0].getblock(str(n), False)[0:354] for n in range(start_height, height)]
        headers_ = self.nodes[0].ws_get_block_headers(hashes)
        assert_equal(exp_headers, headers_)

        mark_logs("Test for retrieving 50 headers", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        self.nodes[0].generate(50)
        height = self.nodes[0].getblockcount()
        hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height)]
        exp_headers = [self.nodes[0].getblock(str(n), False)[0:354] for n in range(start_height, height)]
        self.nodes[0].ws_get_block_headers(hashes)
        headers_ = self.nodes[0].ws_get_block_headers(hashes)
        assert_equal(exp_headers, headers_)


        mark_logs("Test for retrieving 51 headers(Should end up with exception: Invalid parameter)", self.nodes, DEBUG_MODE)
        start_height = self.nodes[0].getblockcount()
        self.nodes[0].generate(51)
        height = self.nodes[0].getblockcount()
        hashes = [self.nodes[0].getblockhash(n) for n in range(start_height, height)]
        try:
            mark_logs("Try to request block headers over the limit", self.nodes, DEBUG_MODE)
            self.nodes[0].ws_get_block_headers(hashes)
            raise RuntimeError("Get block headers. Rquest over the limit(50 headers) passed.")
        except JSONWSException as e:
            print "Exception:", e.error

        t.do_run = False


if __name__ == '__main__':
    ws_messages().main()