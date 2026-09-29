use crate::repo::Repo;

pub struct Service {
    repo: Repo,
}

impl Service {
    pub fn new() -> Service {
        Service { repo: Repo }
    }

    pub fn handle(&self, name: &str) -> bool {
        self.repo.save(name)
    }
}
