"""Parent-scoped identities for each mounted browser control instance."""

import uuid


class NodeIdentities:
    def __init__(self):
        self.current = {}
        self.pending = {}
        self.serial = 0
        self.session = uuid.uuid4().hex

    def begin(self):
        self.pending = {}

    def assign(self, node, parent='document', index=0):
        if node is None:
            return
        key = node.key
        token = ('index', index) if key is None else ('key', type(key).__name__, repr(key))
        identity = (parent, node.node_type, token)
        if identity in self.pending:
            raise ValueError('Duplicate sibling key: %r' % key)
        node_id = self.current.get(identity)
        if node_id is None:
            self.serial += 1
            node_id = 'node-%s-%s' % (self.session, self.serial)
        self.pending[identity] = node_id
        node.props['__browser_id__'] = node_id
        for child_index, child in enumerate(node.children):
            self.assign(child, node_id, child_index)

    def finish(self):
        self.current = self.pending
