class Instruction:
    def __init__(self, cycle, processor_id, opcode, args):
        self.cycle = cycle
        self.processor_id = processor_id
        self.opcode = opcode
        self.args = args

    def __repr__(self):
        return (
            f"Instruction(cycle={self.cycle}, "
            f"processor_id={self.processor_id}, "
            f"opcode={self.opcode}, args={self.args})"
        )