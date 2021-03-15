from typing import List, Tuple, Any
import click
from click import Command

class AlternateArgListCmd(Command):
    """
    click_ decorator class to allow multiple arguments on the same command
    source: https://stackoverflow.com/a/66573792/1597707
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alternate_arglist_handlers: List[Tuple[Command, Any]] = [(self, super())]
        self.alternate_self: Command = self

    def alternate_arglist(self, *args, **kwargs):
        """
        Return the decorator method
        """
        def _decorator(f):
            command = click.decorators.command(*args, **kwargs)(f)
            self.alternate_arglist_handlers.append((command, command))

            # verify we have no options defined and then copy options from base command
            options = [o for o in command.params if isinstance(o, click.Option)]
            if options:
                raise click.ClickException(
                    f'Options not allowed on {type(self).__name__}: {[o.name for o in options]}')
            command.params.extend(o for o in self.params if isinstance(o, click.Option))
            return command

        return _decorator

    def make_context(self, info_name, args, parent=None, **extra):
        """
        Attempt to build a context for each variant, use the first that succeeds
        """
        orig_args = list(args)
        for handler, handler_super in self.alternate_arglist_handlers:
            if handler_super:
                args[:] = list(orig_args)
                self.alternate_self = handler
                try:
                    return handler_super.make_context(info_name, args, parent, **extra)
                except click.UsageError:
                    pass

        # if all alternates fail, return the error message for the first command defined
        args[:] = orig_args
        return super().make_context(info_name, args, parent, **extra)

    def invoke(self, ctx):
        """
        Use the callback for the appropriate variant
        """
        if self.alternate_self.callback is not None:
            return ctx.invoke(self.alternate_self.callback, **ctx.params)
        return super().invoke(ctx)

    def format_usage(self, ctx, formatter):
        """
        Build a Usage for each variant
        """
        prefix = "Usage: "
        for _, handler_super in self.alternate_arglist_handlers:
            if handler_super:
                pieces = handler_super.collect_usage_pieces(ctx)
                formatter.write_usage(ctx.command_path, " ".join(pieces), prefix=prefix)
                prefix = " " * len(prefix)
