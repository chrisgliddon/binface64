# BF64 Collision Examples

Use these current examples to choose engine primitives before writing custom collision logic.

## Character Body Movement

`n64/examples/char_body/src/user/Controller.cpp` uses the runtime `CharBody` component:

```cpp
auto &body = obj.getComponent<P64::Comp::CharBody>()->getBody();

body.inputVelocity = data->lastVel;

if(pressed.a && data->coyoteTimer > 0.0f) {
  body.setVelocity(body.getVelocity() + body.getSettings().up * JUMP_SPEED);
}

body.moveAndSlide(deltaTime);
```

Pattern:

- Read input.
- Compute velocity in the body's current up-plane.
- Set `inputVelocity`.
- Apply jump/teleport/special cases.
- Call `moveAndSlide(deltaTime)` once per update.

## Floor Raycast

`n64/examples/jam25/src/user/Coin.cpp` casts toward the floor and stores the hit:

```cpp
Coll::Raycast ray = Coll::Raycast::create(
  obj.pos + fm_vec3_t{0.0f, 5.0f, 0.0f},
  {0.0f, -1.0f, 0.0f},
  100.0f,
  Coll::RaycastColliderTypeFlags::ALL,
  false,
  0x08
);
obj.getScene().getCollision().raycast(ray, data->floorCast);
```

Pattern:

- Cache raycast results when possible.
- Avoid per-frame casts for far-away or invisible props.
- Use masks intentionally; unexplained masks are hard to debug later.

## Collision Event

`Coin.cpp` handles player collection:

```cpp
void onCollision(Object& obj, Data *data, const Coll::CollEvent& event)
{
  if(!event.otherObject)return;
  if(event.otherObject->id != User::ctx.controlledId)return;
  obj.remove();
}
```

Rules:

- Always null-check `event.otherObject`.
- Filter by id, component, tag-equivalent, or event type before mutating scene state.
- Keep collision callbacks short; expensive work belongs in update systems or spawned effects.

## Acceptance Check

Run scene validation, then build/run:

```bash
./bf64 scene validate --project <project> --json
./bf64 build --execute --project <project> --pyrite64-binary ./pyrite64 --json
./bf64 run --project <project> --emulator ares --json
```
