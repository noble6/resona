"""Desktop Entry Exec quoting, which is not shell quoting."""


def exec_line(arguments: list[str]) -> str:
    # GIO checks the executable before expanding %% field codes. Keep a percent
    # in the executable path in an argument instead, where expansion is defined.
    if arguments and "%" in arguments[0]:
        arguments = ["/usr/bin/env", "--", *arguments]

    def quote(argument):
        argument = argument.replace("%", "%%")
        for char in ("\\", '"', "`", "$"):
            argument = argument.replace(char, "\\" + char)
        # Desktop string escapes are decoded before Exec argument quoting.
        argument = argument.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return '"' + argument + '"'

    return " ".join(quote(argument) for argument in arguments)
