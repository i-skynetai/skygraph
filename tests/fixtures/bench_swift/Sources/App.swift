func run() -> Bool {
    let s = Service(repo: Repo())
    return s.handle("x")
}
