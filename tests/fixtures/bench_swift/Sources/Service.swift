class Service {
    private let repo: Repo

    init(repo: Repo) {
        self.repo = repo
    }

    func handle(_ name: String) -> Bool {
        return repo.save(name)
    }
}
