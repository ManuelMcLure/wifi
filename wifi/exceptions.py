class WifiError(Exception):
    pass


class ConnectionError(WifiError):
    pass


class InterfaceError(WifiError):
    pass


class BindError(WifiError):
    pass
