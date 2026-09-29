require_relative 'repo'

class Service
  def initialize
    @repo = Repo.new
  end

  def handle(name)
    @repo.save(name)
  end
end
