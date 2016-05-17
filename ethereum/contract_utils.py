from copy import deepcopy

from ethereum import blocks
from ethereum import processblock
from ethereum import slogging
from ethereum import exceptions
from ethereum.transactions import Transaction
from ethereum.trie import Trie
from ethereum.utils import normalize_address, denoms

log = slogging.get_logger('contract_utils')

DEFAULT_SENDER = None
DEFAULT_GASPRICE = 60 * denoms.shannon
DEFAULT_VALUE = 0
DEFAULT_STARTGAS = 25000
DEFAULT_DATA = b''


def transact(block, to, privkey, chainservice, sender=DEFAULT_SENDER, gasprice=DEFAULT_GASPRICE,
             value=DEFAULT_VALUE, data=DEFAULT_DATA, startgas=DEFAULT_STARTGAS):
    """
    Allows to trasact to the blockchain directly
    :param block: the current block
    :param to: address of the receiver (can be empty for contract creation)
    :param privkey: the private key used to sign the transaction being sent
    :param chainservice: the chain object to which we want to add the transaction
    :param sender: the address of the sender
    :param gasprice: the gasprice for the transaction
    :param value: the value of the transaction
    :param data: the data of the transaction
    :param startgas: the startgas used for the transaction
    :return: transaction object
    """
    sender = normalize_address(sender)
    to = normalize_address(to, allow_blank=True)
    nonce = block.get_nonce(sender)
    tx = Transaction(nonce, gasprice, startgas, to, value, data)
    tx.sign(privkey)
    assert tx.sender == sender
    chainservice.add_transaction(tx, origin=None, force_broadcast=True)
    return tx


def call(block, to, sender=DEFAULT_SENDER, gasprice=DEFAULT_GASPRICE,
         value=DEFAULT_VALUE, data=DEFAULT_DATA, startgas=DEFAULT_STARTGAS):
    """
    Allows to call the blockchain directly
    :param block: the current block
    :param to: the address of the receiver (can be empty)
    :param sender: the address of the sender
    :param gasprice: the gasprice for the transaction
    :param value: the value of the transaction
    :param data: the data of the transaction
    :param startgas: the startgas used for the transaction
    :return: result of the call if it was successful, None otherwise
    """
    block_state_root_before_tx = block.state_root
    snapshot_before = block.snapshot()
    tx_root_before = snapshot_before['txs'].root_hash

    test_block = None

    if block.has_parent():
        parent = block.get_parent()
        test_block = block.init_from_parent(parent, block.coinbase, timestamp=block.timestamp)
        for btx in block.get_transactions():
            success, output = processblock.apply_transaction(test_block, btx)
            assert success == True
    else:
        test_block = blocks.genesis(block.db)
        original = {key: value for key, value in snapshot_before.items() if key != 'txs'}
        original = deepcopy(original)
        original['txs'] = Trie(snapshot_before['txs'].db, snapshot_before['txs'].root_hash)
        test_block = blocks.genesis(block.db)
        test_block.revert(original)

    nonce = block.get_nonce(sender)
    sender = normalize_address(sender)
    to = normalize_address(to, allow_blank=True)
    startgas = startgas if startgas > 0 else test_block.gas_limit - test_block.gas_used
    tx = Transaction(nonce, gasprice, startgas, to, value, data)
    tx.sender = sender

    success = False
    output = None

    try:
        success, output = processblock.apply_transaction(test_block, tx)
    except exceptions.InvalidTransaction as err:
        log.debug('Invalid transaction: {}'.format(err))

    assert block.state_root == block_state_root_before_tx
    snapshot_after = block.snapshot()
    assert snapshot_after == snapshot_before
    assert snapshot_after['txs'].root_hash == tx_root_before

    if success:
        return output
    else:
        return None
