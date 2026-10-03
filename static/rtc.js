// WebRTC with the camera computer's MediaMTX; the dashboard server only relays the offers (and checks the login).

function rtcGathered(pc) {
  // Non-trickle WHIP/WHEP: send the offer once candidates are known (or after 2 s with what we have).
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise(resolve => {
    pc.addEventListener('icegatheringstatechange', () => pc.iceGatheringState === 'complete' && resolve());
    setTimeout(resolve, 2000);
  });
}

// kind: 'listen' (microphone), 'talk' (speaker) or 'video' (light video). Returns the session id for rtcHangup.
async function rtcNegotiate(kind, pc, cameraId) {
  await pc.setLocalDescription(await pc.createOffer());
  await rtcGathered(pc);
  const answer = await api(`/api/intercom/${kind}`, {method: 'POST', body: JSON.stringify({camera_id: cameraId, sdp: pc.localDescription.sdp})});
  await pc.setRemoteDescription({type: 'answer', sdp: answer.sdp});
  return answer.session;
}

function rtcHangup(cameraId, kind, session) {
  if (!session) return Promise.resolve();
  return api('/api/intercom/hangup', {method: 'POST', keepalive: true, body: JSON.stringify({camera_id: cameraId, kind, session})}).catch(() => {});
}
