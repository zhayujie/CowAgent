import heapq


class SortedDict(dict):
    def __init__(self, sort_func=lambda k, v: k, init_dict=None, reverse=False):
        if init_dict is None:
            init_dict = []
        if isinstance(init_dict, dict):
            init_dict = init_dict.items()
        self.sort_func = sort_func
        self.sorted_keys = None
        self.reverse = reverse
        self.heap = []
        for k, v in init_dict:
            self[k] = v

    def __setitem__(self, key, value):
        if key in self:
            super().__setitem__(key, value)
            for i, (_priority, k) in enumerate(self.heap):
                if k == key:
                    self.heap[i] = (self.sort_func(key, value), key)
                    heapq.heapify(self.heap)
                    break
            self.sorted_keys = None
        else:
            super().__setitem__(key, value)
            heapq.heappush(self.heap, (self.sort_func(key, value), key))
            self.sorted_keys = None

    def __delitem__(self, key):
        super().__delitem__(key)
        for i, (_priority, k) in enumerate(self.heap):
            if k == key:
                del self.heap[i]
                heapq.heapify(self.heap)
                break
        self.sorted_keys = None

    def keys(self):
        if self.sorted_keys is None:
            self.sorted_keys = [k for _, k in sorted(self.heap, reverse=self.reverse)]
        return self.sorted_keys

    def items(self):
        if self.sorted_keys is None:
            self.sorted_keys = [k for _, k in sorted(self.heap, reverse=self.reverse)]
        sorted_items = [(k, self[k]) for k in self.sorted_keys]
        return sorted_items

    def _update_heap(self, key):
        for i, (priority, k) in enumerate(self.heap):
            if k == key:
                new_priority = self.sort_func(key, self[key])
                if new_priority != priority:
                    self.heap[i] = (new_priority, key)
                    heapq.heapify(self.heap)
                    self.sorted_keys = None
                break

    def __iter__(self):
        return iter(self.keys())

    def __repr__(self):
        return f"{type(self).__name__}({dict(self)}, sort_func={self.sort_func.__name__}, reverse={self.reverse})"
