import datetime
import base64
import json
import pickle
import multiprocessing.shared_memory

from . import qt_util
from .shmem import SharedNDArray

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

try:
    import msgpack
    HAVE_MSGPACK = True
except ImportError:
    HAVE_MSGPACK = False

from .proxy import ObjectProxy
from .shmem import SharedNDArray


#: dict containing {name : SerializerSubclass} for all supported serializers
all_serializers = {}  # type_str: class


# Any type that is not supported by json/msgpack must be encoded as a dict.
# To distinguish these from plain dicts, we include a unique key in them:
encode_key = '___type_name___'


# Object types to be serialized by default. This applies when passing
# arguments to a remote procedure and when returning results. All other
# types will be sent by proxy if a server is available; otherwise an 
# exceotion will be raised.
default_serialize_types = (
    ObjectProxy, type(None), str, bytes, int, float, tuple, list, dict, bool,
    datetime.datetime, datetime.date,
    multiprocessing.shared_memory.SharedMemory, SharedNDArray, 
)

if HAVE_NUMPY:
    default_serialize_types += (np.number, np.bool_, np.dtype, np.ndarray)

if qt_util.HAVE_QT:
    from . import qt
    default_serialize_types += (
        qt.QMatrix4x4, qt.QMatrix3x3, qt.QMatrix2x2, qt.QTransform, 
        qt.QVector3D, qt.QVector4D, qt.QQuaternion,
        qt.QPoint, qt.QSize, qt.QRect, qt.QLine, qt.QLineF,
        qt.QPointF, qt.QSizeF, qt.QRectF,
    )


class Serializer:
    """Base serializer class on which msgpack and json serializers 
    (and potentially others) are built.
    
    Subclasses must be registered by adding to the ``all_serializers`` global.
    
    Supports ndarray, date, datetime, and bytes for transfer in addition to the
    standard types supported by json and msgpack. All other types are converted
    to an object proxy that can be used to access methods / attributes of the object
    remotely (this requires that the object be known to an RPC server).
    
    """
    def __init__(self):
        self._server = None
        self._serialize_types = default_serialize_types
        self._proxy_opts = None
    
    @property
    def server(self):
        if self._server is None:
            # get the current server for this thread, if one exists
            from .server import RPCServer
            self._server = RPCServer.get_server()
        return self._server
    
    def dumps(self, obj, server, serialize_types):
        """Convert obj to serialized string.
        """
        raise NotImplementedError()

    def loads(self, msg, server, proxy_opts):
        """Convert from serialized string to python object.
        
        Proxies that reference objects owned by the server are converted back
        into the local object. All other proxies are left as-is.
        """
        raise NotImplementedError()

    def encode(self, obj):
        """Convert various types to serializable objects.
        
        Provides support for ndarray, datetime, date, and None. Other types
        are converted to proxies.
        """
        if not isinstance(obj, self._serialize_types):
            # If this object type is not in server.no_proxy_types, then send by proxy.
            if self.server is None:
                raise TypeError("Cannot make proxy to %r without proxy server." % obj)
            obj = self.server.get_proxy(obj)

        if HAVE_NUMPY and isinstance(obj, np.ndarray):
            if not obj.flags['C_CONTIGUOUS']:
                obj = np.ascontiguousarray(obj)
            assert(obj.flags['C_CONTIGUOUS'])
            return {encode_key: 'ndarray',
                    'data': obj.tobytes(),
                    'dtype': str(obj.dtype),
                    'shape': obj.shape}
        elif isinstance(obj, ObjectProxy):
            ser = {encode_key: 'proxy'}
            ser.update(obj.__getstate__())
            return ser
        elif isinstance(obj, datetime.datetime):
            return {encode_key: 'datetime',
                    'data': obj.strftime('%Y-%m-%dT%H:%M:%S.%f')}
        elif isinstance(obj, datetime.date):
            return {encode_key: 'date',
                    'data': obj.strftime('%Y-%m-%d')}
        elif isinstance(obj, tuple):
            return {encode_key: 'tuple', 'data': list(obj)}
        elif obj is None:
            return {encode_key: 'none'}
        elif HAVE_NUMPY and isinstance(obj, (np.number, np.bool_)):
            if isinstance(obj, np.bool_):
                val = bool(obj)
            elif isinstance(obj, np.integer):
                val = int(obj)
            elif isinstance(obj, np.floating):
                val = float(obj)
            else:
                raise TypeError("Unhandled numpy scalar type: %s" % type(obj))

            return {
                encode_key: 'np_number',
                'dtype': obj.dtype,
                'value': val
            }
        else:
            # All other types are pickled. 
            # TODO: reduce dependence on pickle -- we could technically
            # pickle all basic types, but the result is difficult to parse outside
            # of python. Ideally serializers can be used to communicate with
            # non-python processes. 
            return {
                encode_key: 'pickle',
                'pickle_str': pickle.dumps(obj),
            }

    def decode(self, dct):
        """Convert from serializable objects back to original types.
        """
        if isinstance(dct, dict):
            type_name = dct.pop(encode_key, None)
            if type_name is None:
                return dct
            if type_name == 'ndarray':
                if not HAVE_NUMPY:
                    raise ImportError("numpy is required to deserialize ndarray.")
                dt = dct['dtype']
                if dt.startswith('['):
                    #small hack to have a list
                    d = {}
                    exec('dtype='+dt, None, d)
                    dt = d['dtype']
                return np.frombuffer(dct['data'], dtype=dt).reshape(dct['shape'])
            elif type_name == 'pickle':
                return pickle.loads(dct['pickle_str'])
            elif type_name == 'np_number':
                return dct['dtype'].type(dct['value'])
            elif type_name == 'datetime':
                return datetime.datetime.strptime(dct['data'], '%Y-%m-%dT%H:%M:%S.%f')
            elif type_name == 'date':
                return datetime.datetime.strptime(dct['data'], '%Y-%m-%d').date()
            elif type_name == 'tuple':
                return tuple(dct['data'])
            elif type_name == 'none':
                return None
            elif type_name == 'proxy':
                if 'attributes' in dct:
                    dct['attributes'] = tuple(dct['attributes'])
                proxy = ObjectProxy(**dct)
                if self._proxy_opts is not None:
                    proxy._set_proxy_options(**self._proxy_opts)
                if self.server is not None and proxy._rpc_addr == self.server.address:
                    return self.server.unwrap_proxy(proxy)
                else:
                    return proxy
        return dct


"""
TODO: handle unwrapping proxies in PickleSerializer

class PickleSerializer(Serializer):
    
    # used to tell server how to unserialize messages
    type = 'pickle'
    
    def __init__(self):
        Serializer.__init__(self)

    def dumps(self, obj, server, serialize_types):
        return pickle.dumps(obj)

    def loads(self, msg, server, proxy_opts):
        return pickle.loads(msg)

        
all_serializers[PickleSerializer.type] = PickleSerializer
"""


class MsgpackSerializer(Serializer):
    """Class for serializing objects using msgpack.
    
    Supports ndarray, date, datetime, and bytes for transfer in addition to the
    standard list supported by msgpack. All other types are converted to an
    object proxy that can be used to access methods / attributes of the object
    remotely (this requires that the object be owned by an RPC server).
    
    Note that tuples are converted to lists in transit. See:
    https://github.com/msgpack/msgpack-python/issues/98
    """
    
    # used to tell server how to unserialize messages
    type = 'msgpack'
    
    def __init__(self):
        assert HAVE_MSGPACK
        Serializer.__init__(self)
    
    def dumps(self, obj, server, serialize_types):
        """Convert obj to msgpack string.
        """
        self._server = server
        self._serialize_types = serialize_types or default_serialize_types
        return msgpack.dumps(obj, use_bin_type=True, default=self.encode, strict_types=True)

    def loads(self, msg, server, proxy_opts):
        """Convert from msgpack string to python object.
        
        Proxies that reference objects owned by the server are converted back
        into the local object. All other proxies are left as-is.
        """
        self._server = server
        self._proxy_opts = proxy_opts
        ## use_list=False because we are more likely to care about transmitting
        ## tuples correctly (because they are used as dict keys).
        #return msgpack.loads(msg, encoding='utf8', use_list=False, object_hook=self.decode)

        #Return lists/tuples as lists because json can't be configured otherwise
        return msgpack.loads(msg, object_hook=self.decode)

if HAVE_MSGPACK:
    all_serializers[MsgpackSerializer.type] = MsgpackSerializer


class JsonSerializer(Serializer):
    
    # used to tell server how to unserialize messages
    type = 'json'
    
    def __init__(self):
        Serializer.__init__(self)
        
        # We require a custom class to overrode json encode behavior.
        class EnhancedJSONEncoder(json.JSONEncoder):
            def default(self2, obj):
                obj2 = self.encode(obj)
                if obj is obj2:
                    return json.JSONEncoder.default(self, obj)
                else:
                    return obj2
        self.EnhancedJSONEncoder = EnhancedJSONEncoder
    
    def dumps(self, obj, server, serialize_types):
        self._server = server
        self._serialize_types = serialize_types or default_serialize_types
        return json.dumps(obj, cls=self.EnhancedJSONEncoder).encode()
    
    def loads(self, msg, server, proxy_opts):
        self._server = server
        self._proxy_opts = proxy_opts
        return json.loads(msg.decode(), object_hook=self.decode)

    def encode(self, obj):
        if HAVE_NUMPY and isinstance(obj, np.ndarray):
            # JSON doesn't support bytes, so we use base64 encoding instead:
            if not obj.flags['C_CONTIGUOUS']:
                obj = np.ascontiguousarray(obj)
            assert(obj.flags['C_CONTIGUOUS'])
            return {encode_key: 'ndarray',
                    'data': base64.b64encode(obj.data).decode(),
                    'dtype': str(obj.dtype),
                    'shape': obj.shape}
        elif isinstance(obj, bytes):
            return {encode_key: 'bytes',
                    'data': base64.b64encode(obj).decode()}
        elif obj is None:
            # JSON does support None/null:
            return None
        return Serializer.encode(self, obj)

    def decode(self, dct):
        if isinstance(dct, dict):
            type_name = dct.get(encode_key, None)
            if type_name == 'ndarray':
                if not HAVE_NUMPY:
                    raise ImportError("numpy is required to deserialize ndarray.")
                data = base64.b64decode(dct['data'])
                return np.frombuffer(data, dct['dtype']).reshape(dct['shape'])
            elif type_name == 'bytes':
                return base64.b64decode(dct['data'])
            
            return Serializer.decode(self, dct)
        return dct

all_serializers[JsonSerializer.type] = JsonSerializer
