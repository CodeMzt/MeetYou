import { useCallback, useEffect, useRef, useState } from 'react'
import { createClientWsUrl } from '../../clientApi'
import { fetchWithAuth } from '../../apiClient'
import { parseHealthEnvelope } from '../../protocolClient'
import type { ClientContext } from './useClientContext'

export function useMeetYouSocket(
  baseUrl: string,
  clientContext: ClientContext | null,
  applyClientWsUpdate: (rawPayload: unknown) => void,
  dispatchTransport: any
) {
  const clientWsRef = useRef<WebSocket | null>(null)
  const clientReconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const [clientConnectionState, setClientConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetchWithAuth(`${baseUrl}/health`)
      if (!response.ok) {
        return
      }
      const health = parseHealthEnvelope(await response.json())
      if (!health) {
        return
      }
      dispatchTransport({ type: 'health', health })
    } catch (error) {
      console.error('Failed to refresh health:', error)
    }
  }, [baseUrl, dispatchTransport])

  const sendClientWsCommand = useCallback((payload: Record<string, unknown>) => {
    const ws = clientWsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const connectClientWs = useCallback(() => {
    if (!clientContext?.threadId) {
      return
    }
    if (
      clientWsRef.current?.readyState === WebSocket.OPEN ||
      clientWsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    clearTimeout(clientReconnectTimeoutRef.current)
    setClientConnectionState('connecting')

    void (async () => {
      const url = await createClientWsUrl(baseUrl, clientContext.threadId)
      if (clientWsRef.current?.readyState === WebSocket.OPEN || clientWsRef.current?.readyState === WebSocket.CONNECTING) {
        return
      }
      const ws = new WebSocket(url)
      clientWsRef.current = ws

      ws.onmessage = (event) => {
        if (clientWsRef.current !== ws) {
          return
        }

        try {
          applyClientWsUpdate(JSON.parse(event.data))
        } catch (error) {
          console.error('Client WS parse error:', error)
        }
      }

      ws.onopen = () => {
        if (clientWsRef.current !== ws) {
          ws.close()
          return
        }
        setClientConnectionState('connected')
        void refreshHealth()
      }

      ws.onclose = () => {
        if (clientWsRef.current !== ws) {
          return
        }
        clientWsRef.current = null
        setClientConnectionState('disconnected')
        dispatchTransport({ type: 'set_connection_state', connectionState: 'disconnected' })
        clientReconnectTimeoutRef.current = setTimeout(() => {
          if (!clientWsRef.current) {
            connectClientWs()
          }
        }, 3000)
      }

      ws.onerror = (error) => {
        if (clientWsRef.current !== ws) {
          return
        }
        console.error('Client WS Error:', error)
      }
    })()
  }, [applyClientWsUpdate, baseUrl, clientContext, dispatchTransport, refreshHealth])

  useEffect(() => {
    connectClientWs()
  }, [connectClientWs])

  useEffect(() => {
    return () => {
      clearTimeout(clientReconnectTimeoutRef.current)
      const clientWs = clientWsRef.current
      clientWsRef.current = null
      clientWs?.close()
    }
  }, [])

  return {
    clientConnectionState,
    setClientConnectionState,
    sendClientWsCommand,
    refreshHealth,
  }
}
