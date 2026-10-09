import react from '@vitejs/plugin-react'
import { defineConfig, type PluginOption } from 'vite'
import cesiumImport from 'vite-plugin-cesium'

// The plugin ships CJS-style typings that NodeNext resolution sees as a namespace; unwrap the default.
type CesiumPlugin = () => PluginOption
const cesium = ((cesiumImport as unknown as { default?: CesiumPlugin }).default ??
  (cesiumImport as unknown as CesiumPlugin))

// vite-plugin-cesium copies Cesium's Workers/Assets/Widgets and sets CESIUM_BASE_URL,
// so the bundled NaturalEarthII imagery works offline with no Ion token.
export default defineConfig({
  plugins: [react(), cesium()],
  server: { port: 5173, strictPort: true },
})
