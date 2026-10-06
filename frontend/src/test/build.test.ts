// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { existsSync, readdirSync, readFileSync, statSync } from "fs"
import { resolve, join } from "path"

describe("Build Output Tests", () => {
  const buildDir = resolve(__dirname, "../../build")

  describe("Build Directory", () => {
    it("should have build directory", () => {
      expect(existsSync(buildDir)).toBe(true)
    })

    it("should contain index.html at root", () => {
      const indexPath = join(buildDir, "index.html")
      expect(existsSync(indexPath)).toBe(true)
    })

    it("should have assets directory", () => {
      const assetsPath = join(buildDir, "assets")
      expect(existsSync(assetsPath)).toBe(true)
    })
  })

  describe("Index HTML", () => {
    it("should have valid HTML structure", () => {
      const indexPath = join(buildDir, "index.html")
      if (existsSync(indexPath)) {
        const content = readFileSync(indexPath, "utf-8")
        expect(content).toContain("<!DOCTYPE html>")
        expect(content).toContain("<html")
        expect(content).toContain("<head>")
        expect(content).toContain("<body>")
        expect(content).toContain('<div id="root">')
      }
    })

    it("should reference bundled JavaScript files", () => {
      const indexPath = join(buildDir, "index.html")
      if (existsSync(indexPath)) {
        const content = readFileSync(indexPath, "utf-8")
        // Should have script tags with module type
        expect(content).toMatch(/<script[^>]*type="module"[^>]*>/i)
      }
    })

    it("should reference bundled CSS files", () => {
      const indexPath = join(buildDir, "index.html")
      if (existsSync(indexPath)) {
        const content = readFileSync(indexPath, "utf-8")
        // Should have link tags for stylesheets
        expect(content).toMatch(/<link[^>]*rel="stylesheet"[^>]*>/i)
      }
    })
  })

  describe("Asset Files", () => {
    it("should contain JavaScript files", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const jsFiles = files.filter(f => f.endsWith(".js"))
        expect(jsFiles.length).toBeGreaterThan(0)
      }
    })

    it("should contain CSS files", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const cssFiles = files.filter(f => f.endsWith(".css"))
        expect(cssFiles.length).toBeGreaterThan(0)
      }
    })

    it("should have minified JavaScript files", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const jsFiles = files.filter(f => f.endsWith(".js") && !f.endsWith(".map"))

        // Every file, not the first one listed: the listing order differs by OS. Minified code
        // averages hundreds of characters a line, source about 30-40. A line count doesn't work:
        // three.js keeps its GLSL shaders as multi-line strings, so the 3D scene chunk has thousands.
        for (const file of jsFiles) {
          const content = readFileSync(join(assetsPath, file), "utf-8")
          const averageLine = content.length / content.split("\n").length
          expect(averageLine, file).toBeGreaterThan(100)
        }
      }
    })

    it("should have minified CSS files", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const cssFiles = files.filter(f => f.endsWith(".css") && !f.endsWith(".map"))

        // Every file: the listing order differs by OS
        for (const file of cssFiles) {
          const content = readFileSync(join(assetsPath, file), "utf-8")
          // Minified CSS should have minimal whitespace
          expect(content, file).not.toMatch(/\n\s+/g) // Should not have indented lines
        }
      }
    })
  })

  describe("Source Maps", () => {
    // the build is served publicly by Amplify, so it must not ship the source
    it("should not ship source maps", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        expect(readdirSync(assetsPath).filter(f => f.endsWith(".map"))).toEqual([])
      }
    })
  })

  describe("Code Splitting", () => {
    it("should create multiple JavaScript chunks", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const jsFiles = files.filter(f => f.endsWith(".js") && !f.endsWith(".map"))
        // Should have multiple chunks due to code splitting
        expect(jsFiles.length).toBeGreaterThan(1)
      }
    })

    it("should have vendor chunks for libraries", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const jsFiles = files.filter(f => f.endsWith(".js") && !f.endsWith(".map"))

        // Check if there are multiple chunks (indicating code splitting)
        // The exact naming depends on Vite's chunking strategy
        expect(jsFiles.length).toBeGreaterThanOrEqual(2)
      }
    })
  })

  describe("Static Assets", () => {
    it("should copy public assets to build directory", () => {
      const faviconPath = join(buildDir, "favicon.ico")
      expect(existsSync(faviconPath)).toBe(true)
    })

    it("should preserve public asset structure", () => {
      // Check that public assets are at the root of build, not in a subdirectory
      const faviconPath = join(buildDir, "favicon.ico")
      if (existsSync(faviconPath)) {
        const stats = statSync(faviconPath)
        expect(stats.isFile()).toBe(true)
      }
    })
  })

  describe("Build Optimization", () => {
    it("should produce optimized bundle sizes", () => {
      const assetsPath = join(buildDir, "assets")
      if (existsSync(assetsPath)) {
        const files = readdirSync(assetsPath)
        const jsFiles = files.filter(f => f.endsWith(".js") && !f.endsWith(".map"))

        // Check that individual chunks are reasonably sized (not too large)
        jsFiles.forEach(file => {
          const filePath = join(assetsPath, file)
          const stats = statSync(filePath)
          // Individual chunks should typically be under 1MB for good performance
          expect(stats.size).toBeLessThan(1024 * 1024) // 1MB
        })
      }
    })
  })
})
