from graphql import GraphQLError
from graphql import GraphQLResolveInfo as ResolveInfo


class RequireApiPermissionMiddleware:
    def resolve(self, next, root, info: ResolveInfo, **kwargs):
        # Whitelist any queries/mutations that don't require auth
        open_operations = {"tokenAuth", "verifyToken", "refreshToken"}

        if info.field_name in open_operations:
            return next(root, info, **kwargs)

        user = info.context.user
        if not user or not user.has_perm("core.read_api"):
            raise GraphQLError("Permission denied: `read_api` scope required.")
        return next(root, info, **kwargs)
