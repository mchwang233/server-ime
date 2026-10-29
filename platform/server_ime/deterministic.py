"""A finite test fixture, NOT a pinyin converter or a production dictionary."""
from .port import Candidate, Conversion, InputContext, Selection


FIXTURES = {
    "ni": ("你", "呢", "泥", "拟", "逆", "倪", "妮"),
    "hao": ("好", "号", "浩"),
    "nihao": ("你好", "拟好", "你号"),
    "zhongwen": ("中文", "重文"),
}


class DeterministicSession:
    backend_id = "deterministic-fixture-v1"
    deterministic = True

    def __init__(self):
        self.context = InputContext()
        self.current = ()

    def set_context(self, context):
        self.context = context

    def convert(self, composition, cursor):
        # Unknown input has no invented Chinese result. The adapter can commit raw text.
        words = FIXTURES.get(composition, ())
        self.current = tuple(Candidate(f"{composition}:{i}", word, "链路测试")
                             for i, word in enumerate(words))
        return Conversion(composition, cursor, self.current)

    def select(self, candidate_id):
        for candidate in self.current:
            if candidate.id == candidate_id:
                return Selection(candidate.text)
        raise ValueError("candidate no longer exists")

    def reset(self):
        self.current = ()

    def close(self):
        self.reset()


def create_session():
    return DeterministicSession()
