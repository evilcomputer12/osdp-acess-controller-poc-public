import { io } from 'socket.io-client';

const socket = io({ transports: ['websocket', 'polling'], autoConnect: false, withCredentials: true });
export default socket;
