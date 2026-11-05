//  注册前端组件库和状态管理

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import './style.css'
import App from './App.vue'

createApp(App).use(createPinia()).use(ElementPlus).mount('#app')
