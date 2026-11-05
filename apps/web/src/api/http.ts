// 创建前端 HTTP 客户端

import axios from 'axios'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000
})
