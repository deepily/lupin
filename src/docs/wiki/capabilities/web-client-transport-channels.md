---
capability: web-client-transport-channels
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.transport.AudioTransport.defaultBinaryHandler@1b17489297
  - src.lupin_app.static.js.multiplexer.transport.AudioTransport.createAudioTransport@71562ebc1e
  - src.lupin_app.static.js.multiplexer.transport.ConnectionStateMachine.createConnectionStateMachine@6c89789b28
  - src.lupin_app.static.js.multiplexer.transport.QueueTransport.QueueTransportImpl@20f7d305a7
  - src.lupin_app.static.js.multiplexer.transport.QueueTransport.createQueueTransport@19ab8d32a6
  - src.lupin_app.static.js.multiplexer.transport.QueueTransport.stripTrailingSlash@843ca8e789
  - src.lupin_app.static.js.multiplexer.transport.index.createTransports@530a69d8da
  - src.lupin_app.static.js.multiplexer.transport.ws-channel.WSChannelImpl@0792595745
  - src.lupin_app.static.js.multiplexer.transport.ws-channel.createWSChannel@47ae98d95c
  - src.lupin_app.static.js.multiplexer.transport.ws-channel.makeCloseEvent@dc2c5c6863
  - src.lupin_app.static.js.ws-channel.fullJitterDelay@179f5b8acc
  - src.lupin_app.static.js.ws-channel.createChannel@72a431a54f
---
# Web client transport channels

The audio and queue sockets, their connection state machine and the shared channel helpers. [[web-client-transport-and-auth]] describes the transport as a whole.

## What it does
- `AudioTransport.ts`. `defaultBinaryHandler`: Logs the size of a received binary audio frame to the console debug output. `createAudioTransport`: Build an audio transport for `/ws/audio`; no socket opens until `start` is called.
- `ConnectionStateMachine.ts`. `createConnectionStateMachine`: Build a connection state machine that reports on the given bus.
- `QueueTransport.ts`. `QueueTransportImpl`: The transport for `/ws/queue`. `createQueueTransport`: Build a queue transport for `/ws/queue`; no socket opens until `start` is called. `stripTrailingSlash`: Removes any trailing slashes from a URL.
- `index.ts`. `createTransports`: Build the queue and audio transports over one auth manager and one bus.
- `ws-channel.ts`. `WSChannelImpl`: Wraps one WebSocket with a state and a generation counter. `createWSChannel`: Build a channel; it throws if `url` is empty or no WebSocket constructor is available. `makeCloseEvent`: Returns a close event with the given code and reason.
- `ws-channel.js`. `fullJitterDelay`: Full-jitter backoff delay in milliseconds. `createChannel`: Create a per-channel WebSocket state machine.
