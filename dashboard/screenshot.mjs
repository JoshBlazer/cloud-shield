import { chromium } from 'playwright'
import path from 'path'

const OUT = path.resolve('../')

const browser = await chromium.launch()
const page    = await browser.newPage()
await page.setViewportSize({ width: 1400, height: 900 })

// Violations view
await page.goto('http://localhost:4173', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/dash_violations.png` })
console.log('✓ violations')

// My Resources view
await page.goto('http://localhost:4173/my-resources', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/dash_my_resources.png` })
console.log('✓ my-resources')

// Posture view
await page.goto('http://localhost:4173/posture', { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
await page.screenshot({ path: `${OUT}/dash_posture.png` })
console.log('✓ posture')

await browser.close()
