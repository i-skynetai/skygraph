pub struct Repo;

impl Repo {
    pub fn save(&self, name: &str) -> bool {
        !name.is_empty()
    }
}
