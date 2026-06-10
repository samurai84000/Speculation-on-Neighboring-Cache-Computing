from instruction import Instruction


class InstructionLoader:
    @staticmethod
    def load(filename):
        instructions_by_cycle = {}

        with open(filename, "r") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                parts = line.split()

                if len(parts) < 3:
                    raise ValueError(
                        f"Invalid instruction on line {line_number}: {line}"
                    )

                cycle = int(parts[0])
                processor_id = parts[1]
                opcode = parts[2].upper()
                args = parts[3:]

                instruction = Instruction(
                    cycle=cycle,
                    processor_id=processor_id,
                    opcode=opcode,
                    args=args
                )

                if cycle not in instructions_by_cycle:
                    instructions_by_cycle[cycle] = []

                instructions_by_cycle[cycle].append(instruction)

        return instructions_by_cycle