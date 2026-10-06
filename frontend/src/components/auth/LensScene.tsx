import { useEffect, useMemo, useRef, useState, type PointerEvent, type RefObject } from "react"
import { Canvas, useFrame, useThree } from "@react-three/fiber"
import { Environment, Lightformer, MeshTransmissionMaterial } from "@react-three/drei"
import * as THREE from "three"
import { LENS_HALVES } from "@/components/chat/ChatHeader"

// The card is always ink; these match :root in globals.css
const INK = "#161a33"
const AI = "#2e46e8"
const MANGO = "#f2a31b"
const CARD_W = 3.4
const CARD_H = CARD_W / 1.586 // ISO card ratio
const LENS_R = 0.95

type Pointer = RefObject<{ x: number; y: number; active: boolean }>

/** The card face, drawn once: the band's lines on ink, a chip, the bank's name and the last 4 digits. */
function useCardTexture() {
  const [texture, setTexture] = useState<THREE.CanvasTexture | null>(null)
  useEffect(() => {
    let cancelled = false
    let made: THREE.CanvasTexture | null = null
    // The face uses the page's font; draw once it's loaded (or give up and draw anyway)
    document.fonts
      .load('500 64px "Funnel Display"')
      .catch(() => [])
      .then(() => {
        if (cancelled) return
        const w = 1712
        const h = 1080
        const canvas = document.createElement("canvas")
        canvas.width = w
        canvas.height = h
        const g = canvas.getContext("2d")!
        g.beginPath()
        g.roundRect(0, 0, w, h, 72)
        g.clip()
        g.fillStyle = INK
        g.fillRect(0, 0, w, h)

        // Cobalt lines fade out down the card while mango lines fade in
        const ai = g.createLinearGradient(0, 0, 0, h)
        ai.addColorStop(0.05, AI)
        ai.addColorStop(0.85, "rgba(46,70,232,0)")
        const human = g.createLinearGradient(0, 0, 0, h)
        human.addColorStop(0.15, "rgba(242,163,27,0)")
        human.addColorStop(0.95, MANGO)
        for (let x = 0; x < w; x += 24) {
          g.fillStyle = ai
          g.fillRect(x, 0, 8, h)
          g.fillStyle = human
          g.fillRect(x + 12, 0, 8, h)
        }

        // Chip
        const chip = g.createLinearGradient(150, 380, 360, 540)
        chip.addColorStop(0, "#f7d27a")
        chip.addColorStop(1, "#c98a12")
        g.fillStyle = chip
        g.beginPath()
        g.roundRect(150, 380, 210, 160, 28)
        g.fill()

        g.fillStyle = "#ffffff"
        g.font = '500 72px "Funnel Display", sans-serif'
        g.fillText("LATAM Bank", 150, 210)
        g.font = '400 96px "Funnel Display", sans-serif'
        g.letterSpacing = "8px"
        g.fillText("••••  4821", 150, 930)

        // The brand mark, bottom right
        g.translate(w - 250, h - 260)
        g.scale(6, 6)
        g.fillStyle = AI
        g.fill(new Path2D(LENS_HALVES.ai))
        g.fillStyle = MANGO
        g.fill(new Path2D(LENS_HALVES.human))

        made = new THREE.CanvasTexture(canvas)
        made.colorSpace = THREE.SRGBColorSpace
        made.anisotropy = 8
        setTexture(made)
      })
    return () => {
      cancelled = true
      made?.dispose()
    }
  }, [])
  return texture
}

/** A biconvex lens: two spherical caps meeting at the rim, facing the camera. */
function lensGeometry(radius = LENS_R, sag = 0.2, steps = 32) {
  const r = (radius * radius + sag * sag) / (2 * sag)
  const height = (x: number) => sag - (r - Math.sqrt(r * r - x * x))
  // Bottom to top: LatheGeometry winds faces from the profile's order, and this order gives
  // outward normals, which is what makes the transmission magnify instead of shrink
  const profile: THREE.Vector2[] = []
  for (let i = 0; i <= steps; i++)
    profile.push(new THREE.Vector2((radius * i) / steps, -height((radius * i) / steps)))
  for (let i = steps; i >= 0; i--)
    profile.push(new THREE.Vector2((radius * i) / steps, height((radius * i) / steps)))
  const geometry = new THREE.LatheGeometry(profile, 96)
  geometry.rotateX(Math.PI / 2)
  return geometry
}

/** Fits the card in the frame on any aspect: a wide phone strip or a tall desktop panel. */
function useFit() {
  const { viewport } = useThree()
  return Math.min(1, (viewport.width * 0.8) / CARD_W, (viewport.height * 0.78) / CARD_H)
}

const damp = (from: number, to: number, rate: number, dt: number) =>
  from + (to - from) * (1 - Math.exp(-rate * dt))

function Card({ pointer, still }: { pointer: Pointer; still: boolean }) {
  const texture = useCardTexture()
  const ref = useRef<THREE.Group>(null!)
  const fit = useFit()
  useFrame((_, dt) => {
    // A slight turn toward the pointer; with reduced motion the card holds its pose
    const p = still || !pointer.current.active ? { x: 0, y: 0 } : pointer.current
    ref.current.rotation.y = damp(ref.current.rotation.y, -0.22 + p.x * 0.18, 3, dt)
    ref.current.rotation.x = damp(ref.current.rotation.x, -0.1 - p.y * 0.12, 3, dt)
  })
  return (
    <group ref={ref} scale={fit} rotation={[-0.1, -0.22, 0.04]}>
      {texture && (
        <mesh>
          <planeGeometry args={[CARD_W, CARD_H]} />
          <meshPhysicalMaterial
            map={texture}
            transparent
            roughness={0.45}
            clearcoat={1}
            clearcoatRoughness={0.15}
          />
        </mesh>
      )}
    </group>
  )
}

function Lens({
  pointer,
  still,
  background,
}: {
  pointer: Pointer
  still: boolean
  background: string
}) {
  const ref = useRef<THREE.Group>(null!)
  const geometry = useMemo(() => lensGeometry(), [])
  const { viewport } = useThree()
  const fit = useFit()
  // Rest over the last 4 digits; follow the pointer while it's over the scene
  const rest = { x: -0.62 * fit, y: -0.55 * fit }
  useFrame((_, dt) => {
    const g = ref.current
    const p = pointer.current
    const x = p.active ? (p.x * viewport.width) / 2 : rest.x
    const y = p.active ? (p.y * viewport.height) / 2 : rest.y
    if (still) {
      g.position.set(x, y, 1.4)
      return
    }
    // Tilt toward where it's heading, so it reads as a held lens rather than a sticker
    g.rotation.y = damp(g.rotation.y, (x - g.position.x) * 0.5, 6, dt)
    g.rotation.x = damp(g.rotation.x, -(y - g.position.y) * 0.5, 6, dt)
    g.position.x = damp(g.position.x, x, 4, dt)
    g.position.y = damp(g.position.y, y, 4, dt)
  })
  // Enters from above and settles over the card; with reduced motion it starts in place
  return (
    <group ref={ref} position={[rest.x, still ? rest.y : viewport.height, 1.4]} scale={fit}>
      <mesh geometry={geometry}>
        <MeshTransmissionMaterial
          background={new THREE.Color(background)}
          thickness={1.8}
          ior={1.5}
          chromaticAberration={0.06}
          anisotropicBlur={0.05}
          roughness={0}
          samples={6}
          resolution={768}
        />
      </mesh>
      <mesh>
        <torusGeometry args={[LENS_R, 0.014, 12, 128]} />
        <meshStandardMaterial color="#e8eaf6" metalness={0.9} roughness={0.2} />
      </mesh>
    </group>
  )
}

/** The page's surface color, kept in step with the theme toggle. */
function useCardColor() {
  const read = () =>
    getComputedStyle(document.documentElement).getPropertyValue("--card").trim() || "#ffffff"
  const [color, setColor] = useState(read)
  useEffect(() => {
    const observer = new MutationObserver(() => setColor(read()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
    return () => observer.disconnect()
  }, [])
  return color
}

/** The sign-in hero: a LATAM Bank card under a glass lens that follows the pointer. */
export default function LensScene() {
  const pointer = useRef({ x: 0, y: 0, active: false })
  const background = useCardColor()
  const still = useMemo(() => matchMedia("(prefers-reduced-motion: reduce)").matches, [])
  const track = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    pointer.current = {
      x: ((e.clientX - r.left) / r.width) * 2 - 1,
      y: -(((e.clientY - r.top) / r.height) * 2 - 1),
      active: true,
    }
  }
  return (
    <div
      aria-hidden
      onPointerMove={track}
      onPointerLeave={() => (pointer.current = { ...pointer.current, active: false })}
      className="h-full overflow-hidden rounded-[32px] bg-card"
    >
      {/* ponytail: renders every frame while the page is open; switch to frameloop="demand" if battery matters */}
      {/* flat: no tone mapping, so the scene's colors match the page's CSS */}
      <Canvas flat dpr={[1, 2]} camera={{ position: [0, 0, 7], fov: 35 }}>
        <color attach="background" args={[background]} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[3, 4, 5]} intensity={1.4} />
        {/* Studio lights for the glass and the card's clearcoat, built here instead of downloading an HDR */}
        <Environment resolution={256}>
          <Lightformer form="rect" intensity={3} position={[0, 4, 3]} scale={[8, 1.5, 1]} />
          <Lightformer form="circle" intensity={2} position={[4, -2, 3]} scale={2} color={MANGO} />
          <Lightformer form="circle" intensity={2} position={[-3, 3, 4]} scale={1.5} color={AI} />
        </Environment>
        <Card pointer={pointer} still={still} />
        <Lens pointer={pointer} still={still} background={background} />
      </Canvas>
    </div>
  )
}
